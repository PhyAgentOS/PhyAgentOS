from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from PhyAgentOS.skill_runtime.archive import ArchiveValidator, sha256_file

SCRIPT = Path(__file__).parents[1] / "scripts" / "package_skill.py"


def _skill_source(root: Path, *, version: str = "0.0.1") -> Path:
    """Build a minimal Skill source tree including a dotfile."""
    source = root / "demo-pkg"
    (source / "profiles" / "local").mkdir(parents=True)
    (source / "assets").mkdir()
    (source / "skill.yaml").write_text(
        yaml.safe_dump(
            {
                "manifest_version": 2,
                "name": "demo-pkg",
                "version": version,
                "description": "Packaging test",
                "skill_document": "SKILL.md",
                "gateway_url": "http://127.0.0.1:19002",
                "required_tools": ["demo.run"],
                "profiles": {
                    "local": {
                        "dataflow": "profiles/local/dataflow.yaml",
                        "required_binaries": [],
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (source / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    (source / "profiles" / "local" / "dataflow.yaml").write_text(
        "nodes: []\n", encoding="utf-8"
    )
    (source / "assets" / "model.bin").write_bytes(b"\x00\x01\x02")
    (source / ".hidden").write_text("hidden\n", encoding="utf-8")
    return source


def _run_script(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=cwd,
    )


def _expected_manifest(source: Path) -> dict[str, tuple[int, str]]:
    """Independently hash every payload file in the source tree."""
    expected = {}
    for path in sorted(source.rglob("*")):
        if path.name == "archive-manifest.json":
            continue
        if path.is_file():
            expected[path.relative_to(source).as_posix()] = (
                path.stat().st_size,
                sha256_file(path),
            )
    return expected


def test_package_script_builds_valid_deterministic_bundle(tmp_path: Path) -> None:
    source = _skill_source(tmp_path)
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    first = _run_script(str(source), "--output-dir", str(out1), cwd=tmp_path)
    second = _run_script(str(source), "--output-dir", str(out2), cwd=tmp_path)
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    bundle1 = out1 / "demo-pkg-0.0.1.tar.gz"
    bundle2 = out2 / "demo-pkg-0.0.1.tar.gz"
    assert bundle1.is_file()
    digest = sha256_file(bundle1)
    assert sha256_file(bundle2) == digest
    assert "sha256:" in first.stdout

    ArchiveValidator().extract(
        bundle1,
        tmp_path / "extracted",
        expected_sha256=digest,
    )

    manifest = json.loads(
        (source / "archive-manifest.json").read_text(encoding="utf-8")
    )
    recorded = {entry["path"]: (entry["size"], entry["sha256"]) for entry in manifest["files"]}
    expected = _expected_manifest(source)
    assert recorded == expected
    assert ".hidden" in recorded


def test_package_script_version_override(tmp_path: Path) -> None:
    source = _skill_source(tmp_path)
    out = tmp_path / "out"
    result = _run_script(
        str(source), "--output-dir", str(out), "--version", "0.2.0", cwd=tmp_path
    )
    assert result.returncode == 0, result.stderr
    assert (out / "demo-pkg-0.2.0.tar.gz").is_file()
    raw = yaml.safe_load((source / "skill.yaml").read_text(encoding="utf-8"))
    assert raw["version"] == "0.0.1"


def test_package_script_rejects_symlinks(tmp_path: Path) -> None:
    source = _skill_source(tmp_path)
    (source / "assets" / "leak").symlink_to("../SKILL.md")
    out = tmp_path / "out"
    result = _run_script(str(source), "--output-dir", str(out), cwd=tmp_path)
    assert result.returncode == 1
    assert "symlink" in result.stderr.lower()
    assert not (out / "demo-pkg-0.0.1.tar.gz").exists()


def test_package_script_rejects_hardlinks(tmp_path: Path) -> None:
    source = _skill_source(tmp_path)
    (source / "assets" / "hard").hardlink_to(source / "SKILL.md")
    out = tmp_path / "out"
    result = _run_script(str(source), "--output-dir", str(out), cwd=tmp_path)
    assert result.returncode == 1
    assert "hard link" in result.stderr.lower()
    assert not (out / "demo-pkg-0.0.1.tar.gz").exists()


def test_package_script_refuses_overwrite_without_force(tmp_path: Path) -> None:
    source = _skill_source(tmp_path)
    out = tmp_path / "out"
    first = _run_script(str(source), "--output-dir", str(out), cwd=tmp_path)
    assert first.returncode == 0, first.stderr
    bundle = out / "demo-pkg-0.0.1.tar.gz"
    original = bundle.read_bytes()

    refused = _run_script(str(source), "--output-dir", str(out), cwd=tmp_path)
    assert refused.returncode == 1
    assert "already exists" in refused.stderr
    assert bundle.read_bytes() == original

    forced = _run_script(str(source), "--output-dir", str(out), "--force", cwd=tmp_path)
    assert forced.returncode == 0, forced.stderr
    assert bundle.read_bytes() == original


def test_package_script_requires_skill_files(tmp_path: Path) -> None:
    source = _skill_source(tmp_path)
    (source / "SKILL.md").unlink()
    result = _run_script(str(source), "--output-dir", str(tmp_path / "out"), cwd=tmp_path)
    assert result.returncode == 1
    assert "SKILL.md" in result.stderr

    (source / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    (source / "skill.yaml").unlink()
    result = _run_script(str(source), "--output-dir", str(tmp_path / "out"), cwd=tmp_path)
    assert result.returncode == 1
    assert "skill.yaml" in result.stderr


def test_package_script_missing_source_dir(tmp_path: Path) -> None:
    result = _run_script(str(tmp_path / "nope"), "--output-dir", str(tmp_path / "out"), cwd=tmp_path)
    assert result.returncode == 1
    assert "not found" in result.stderr


def test_package_script_no_validate_flag(tmp_path: Path) -> None:
    source = _skill_source(tmp_path)
    out = tmp_path / "out"
    result = _run_script(str(source), "--output-dir", str(out), "--no-validate", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert (out / "demo-pkg-0.0.1.tar.gz").is_file()
    assert "validation passed" not in result.stdout
