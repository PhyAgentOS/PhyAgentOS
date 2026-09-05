"""Strict, non-persistent API-key file resolution for PAOS configuration."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def read_api_key_file(configured_path: str, *, base_dir: Path) -> str:
    """Read one owner-only API key without following symlinks or persisting it."""
    path = Path(configured_path).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    path = path.absolute()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"api_key_file cannot be opened: {path}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("api_key_file must be a regular file")
        if info.st_uid != os.getuid():
            raise ValueError("api_key_file must be owned by the current user")
        if info.st_mode & 0o077:
            raise ValueError("api_key_file permissions must not grant group/other access")
        if info.st_size == 0 or info.st_size > 16 * 1024:
            raise ValueError("api_key_file must be non-empty and at most 16 KiB")
        raw = os.read(fd, 16 * 1024 + 1)
    finally:
        os.close(fd)
    try:
        key = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("api_key_file must contain UTF-8 text") from exc
    if not key or any(ch.isspace() for ch in key):
        raise ValueError("api_key_file must contain exactly one non-whitespace token")
    lowered = key.lower()
    if lowered in {"your_api_key", "your-api-key", "placeholder", "changeme", "replace_me"}:
        raise ValueError("api_key_file contains a placeholder value")
    return key
