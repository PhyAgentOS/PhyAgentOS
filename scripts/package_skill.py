"""Package a Skill source directory into the standard deterministic .tar.gz bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PhyAgentOS.skill_runtime.archive import ArchiveValidator, sha256_file  # noqa: E402

ARCHIVE_MANIFEST_NAME = "archive-manifest.json"


class PackagingError(RuntimeError):
    """Raised when a Skill bundle cannot be packaged."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="package_skill.py",
        description=(
            "Package a Skill source directory into the standard deterministic "
            ".tar.gz bundle."
        ),
    )
    parser.add_argument(
        "skill_dir",
        help="Skill source directory containing skill.yaml and SKILL.md",
    )
    parser.add_argument(
        "--output-dir",
        default="dist",
        help="Output directory (default: dist)",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Override the version read from skill.yaml",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip post-build ArchiveValidator verification",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing output bundle",
    )
    return parser.parse_args(argv)


def _directory_safe(value: str, label: str) -> None:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise PackagingError(f"Skill {label} is not directory-safe: {value!r}")


def load_skill_identity(skill_dir: Path) -> tuple[str, str]:
    """Read the Skill name and version from skill.yaml."""
    manifest_path = skill_dir / "skill.yaml"
    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PackagingError("cannot parse skill.yaml") from exc
    if not isinstance(data, dict):
        raise PackagingError("skill.yaml must contain a mapping")
    name = data.get("name")
    version = data.get("version")
    if not isinstance(name, str) or not name:
        raise PackagingError("skill.yaml name must be a non-empty string")
    if not isinstance(version, str) or not version:
        raise PackagingError("skill.yaml version must be a non-empty string")
    _directory_safe(name, "name")
    _directory_safe(version, "version")
    return name, version


def regenerate_archive_manifest(skill_dir: Path) -> int:
    """Rewrite archive-manifest.json from the current source tree."""
    files: list[dict[str, int | str]] = []
    for dirpath, dirnames, filenames in os.walk(skill_dir, topdown=True, followlinks=False):
        current = Path(dirpath)
        kept_dirs = []
        for name in dirnames:
            candidate = current / name
            if candidate.is_symlink():
                raise PackagingError(f"Skill source must not contain symlinks: {candidate}")
            kept_dirs.append(name)
        dirnames[:] = kept_dirs
        for name in filenames:
            candidate = current / name
            if candidate.is_symlink():
                raise PackagingError(f"Skill source must not contain symlinks: {candidate}")
            if candidate.stat().st_nlink > 1:
                raise PackagingError(
                    f"Skill source must not contain hard links: {candidate}"
                )
            if current == skill_dir and name == ARCHIVE_MANIFEST_NAME:
                continue
            data = candidate.read_bytes()
            relative = candidate.relative_to(skill_dir).as_posix()
            files.append(
                {
                    "path": relative,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    files.sort(key=lambda entry: str(entry["path"]))
    (skill_dir / ARCHIVE_MANIFEST_NAME).write_text(
        json.dumps({"files": files}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return len(files)


def build_bundle(skill_dir: Path, output_dir: Path, filename: str) -> Path:
    """Build the deterministic .tar.gz via GNU tar piped through gzip."""
    for tool in ("tar", "gzip"):
        if shutil.which(tool) is None:
            raise PackagingError(f"{tool} is required to package a Skill bundle")
    staged = output_dir / f".{filename}.{os.getpid()}.tmp"
    environment = os.environ | {"LC_ALL": "C"}
    # Archive the sorted top-level entries, not ``.`` itself: the bare ``.`` member
    # normalizes to an empty path and is rejected by ArchiveValidator.
    entries = sorted(os.listdir(skill_dir))
    with open(staged, "wb") as output:
        tar_process = subprocess.Popen(
            [
                "tar",
                "--sort=name",
                "--mtime=UTC 1970-01-01",
                "--owner=0",
                "--group=0",
                "--numeric-owner",
                "-C",
                str(skill_dir),
                "-cf",
                "-",
                *entries,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        gzip_process = subprocess.Popen(
            ["gzip", "-n"],
            stdin=tar_process.stdout,
            stdout=output,
            stderr=subprocess.PIPE,
            env=environment,
        )
        assert tar_process.stdout is not None
        tar_process.stdout.close()
        _unused, tar_error = tar_process.communicate()
        _unused, gzip_error = gzip_process.communicate()
    if tar_process.returncode or gzip_process.returncode:
        staged.unlink(missing_ok=True)
        detail = (tar_error or gzip_error).decode(errors="replace").strip()
        raise PackagingError(
            "tar/gzip failed (requires GNU tar with --sort=name): "
            f"{detail or 'unknown error'}"
        )
    return staged


def validate_bundle(archive: Path) -> None:
    """Verify the archive with ArchiveValidator against a fresh extraction."""
    with tempfile.TemporaryDirectory(prefix="paos-skill-package-") as directory:
        ArchiveValidator().extract(
            archive,
            Path(directory) / "extracted",
            expected_sha256=sha256_file(archive),
        )


def main(argv: list[str] | None = None) -> int:
    """Run the packaging pipeline."""
    args = parse_args(argv)
    try:
        skill_dir = Path(args.skill_dir).expanduser().resolve()
        if not skill_dir.is_dir():
            raise PackagingError(f"Skill source directory not found: {args.skill_dir}")
        if not (skill_dir / "skill.yaml").is_file():
            raise PackagingError("Skill source must contain skill.yaml")
        if not (skill_dir / "SKILL.md").is_file():
            raise PackagingError("Skill source must contain SKILL.md")
        name, version = load_skill_identity(skill_dir)
        version = args.version or version
        _directory_safe(version, "version")
        count = regenerate_archive_manifest(skill_dir)
        print(f"Recorded {count} files in archive-manifest.json")
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"{name}-{version}.tar.gz"
        if target.exists() and not args.force:
            raise PackagingError(
                f"Skill bundle already exists: {target} (use --force to overwrite)"
            )
        staged = build_bundle(skill_dir, output_dir, f"{name}-{version}.tar.gz")
        if not args.no_validate:
            validate_bundle(staged)
            print("Skill Bundle archive validation passed")
        os.replace(staged, target)
        print(f"Skill bundle: {target}")
        print(f"sha256: {sha256_file(target)}")
        print(f"size_bytes: {target.stat().st_size}")
    except PackagingError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
