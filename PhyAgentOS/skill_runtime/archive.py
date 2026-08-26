"""Validation and safe extraction for downloaded ``tar.gz`` artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any


class ArchiveError(ValueError):
    """Raised when an archive is malformed, unsafe, or fails integrity checks."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or "\x00" in name
        or "\\" in name
        or (path.parts and path.parts[0].endswith(":"))
    ):
        raise ArchiveError(f"unsafe archive path: {name!r}")
    normalized = PurePosixPath(*(part for part in path.parts if part not in {"", "."}))
    if not normalized.parts:
        raise ArchiveError(f"unsafe archive path: {name!r}")
    return normalized


def _parse_file_manifest(value: Any) -> dict[str, tuple[str, int | None]]:
    if not isinstance(value, dict):
        raise ArchiveError("archive manifest must be a JSON object")
    raw_files = value.get("files")
    result: dict[str, tuple[str, int | None]] = {}
    if isinstance(raw_files, dict):
        iterable = [
            {"path": path, **({"sha256": item} if isinstance(item, str) else item)}
            for path, item in raw_files.items()
            if isinstance(item, (str, dict))
        ]
    elif isinstance(raw_files, list):
        iterable = raw_files
    else:
        raise ArchiveError("archive manifest files must be a list or mapping")
    for item in iterable:
        if not isinstance(item, dict):
            raise ArchiveError("archive manifest file entries must be objects")
        path = _safe_path(item.get("path") if isinstance(item.get("path"), str) else "").as_posix()
        digest = item.get("sha256")
        size = item.get("size")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in digest)
        ):
            raise ArchiveError(f"invalid sha256 for {path}")
        if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size < 0):
            raise ArchiveError(f"invalid size for {path}")
        if path in result:
            raise ArchiveError(f"duplicate archive manifest path: {path}")
        result[path] = (digest.lower(), size)
    return result


class ArchiveValidator:
    """Reject unsafe tar members and verify an embedded per-file manifest."""

    manifest_names = ("archive-manifest.json", ".paos-manifest.json")

    def extract(
        self,
        archive: Path,
        destination: Path,
        *,
        expected_sha256: str | None = None,
    ) -> Path:
        if expected_sha256 and sha256_file(archive) != expected_sha256.lower():
            raise ArchiveError("archive sha256 mismatch")
        compressed_size = archive.stat().st_size
        if compressed_size <= 0:
            raise ArchiveError("archive is empty")
        destination.mkdir(parents=True, exist_ok=False)
        try:
            with tarfile.open(archive, mode="r:gz") as tar:
                members = tar.getmembers()
                files: dict[str, tarfile.TarInfo] = {}
                seen: set[str] = set()
                collision_keys: dict[str, str] = {}
                for member in members:
                    path = _safe_path(member.name).as_posix()
                    if path in seen:
                        raise ArchiveError(f"duplicate archive path: {path}")
                    seen.add(path)
                    collision_key = unicodedata.normalize("NFC", path).casefold()
                    previous = collision_keys.get(collision_key)
                    if previous is not None:
                        raise ArchiveError(
                            f"archive paths collide after normalization: {previous}, {path}"
                        )
                    collision_keys[collision_key] = path
                    if member.issym() or member.islnk():
                        raise ArchiveError(f"links are forbidden in archives: {path}")
                    if not (member.isfile() or member.isdir()):
                        raise ArchiveError(f"special archive member is forbidden: {path}")
                    if member.isfile():
                        files[path] = member

                manifest_path = next((name for name in self.manifest_names if name in files), None)
                if manifest_path is None:
                    raise ArchiveError("archive does not contain an embedded file manifest")
                manifest_handle = tar.extractfile(files[manifest_path])
                if manifest_handle is None:
                    raise ArchiveError("cannot read embedded archive manifest")
                try:
                    expected_files = _parse_file_manifest(json.load(manifest_handle))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise ArchiveError("embedded archive manifest is not valid JSON") from exc

                payload_files = set(files) - set(self.manifest_names)
                if payload_files != set(expected_files):
                    missing = sorted(set(expected_files) - payload_files)
                    extra = sorted(payload_files - set(expected_files))
                    raise ArchiveError(
                        f"archive manifest file set mismatch; missing={missing}, extra={extra}"
                    )

                for member in members:
                    path = _safe_path(member.name)
                    if path.as_posix() in self.manifest_names:
                        continue
                    target = destination.joinpath(*path.parts)
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = tar.extractfile(member)
                    if source is None:
                        raise ArchiveError(f"cannot read archive member: {path.as_posix()}")
                    digest = hashlib.sha256()
                    written = 0
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                    with os.fdopen(os.open(target, flags, 0o600), "wb") as output:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            written += len(chunk)
                            if written > member.size:
                                raise ArchiveError(
                                    f"archive member expanded beyond declared size: {path.as_posix()}"
                                )
                            output.write(chunk)
                            digest.update(chunk)
                    if written != member.size or (
                        expected_files[path.as_posix()][1] is not None
                        and written != expected_files[path.as_posix()][1]
                    ):
                        raise ArchiveError(f"file size mismatch: {path.as_posix()}")
                    if (
                        digest.hexdigest() != expected_files[path.as_posix()][0]
                    ):
                        raise ArchiveError(f"file sha256 mismatch: {path.as_posix()}")
                    safe_mode = member.mode & 0o755
                    os.chmod(target, safe_mode or 0o600, follow_symlinks=False)
            return destination
        except Exception:
            import shutil

            shutil.rmtree(destination, ignore_errors=True)
            raise
