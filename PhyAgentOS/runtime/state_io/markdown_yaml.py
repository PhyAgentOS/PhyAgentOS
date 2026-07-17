"""Read and write Markdown files that contain one fenced YAML block."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from PhyAgentOS.runtime.state_io.atomic_file import atomic_write_text

_YAML_BLOCK_RE = re.compile(
    r"(?P<fence>`{3,}|~{3,})\s*yaml\s*\n(?P<body>.*?)(?:\n(?P=fence)\s*)",
    re.DOTALL | re.IGNORECASE,
)


def read_yaml_block(path: Path) -> dict[str, Any]:
    """Read the first YAML fenced block from a Markdown file."""
    text = path.read_text(encoding="utf-8")
    match = _YAML_BLOCK_RE.search(text)
    if match is None:
        raise ValueError(f"{path} does not contain a fenced YAML block")
    payload = yaml.safe_load(match.group("body")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"{path} YAML block must contain a mapping")
    return payload


def _safe_str(val: Any) -> Any:
    """Sanitize strings that may contain newlines to prevent YAML dump bugs.

    PyYAML's safe_dump sometimes produces incorrect indentation for
    multi-line strings (e.g. error tracebacks), resulting in invalid
    YAML blocks in SESSIONS.md.  We replace embedded newlines with
    a single space so the string stays single-line and safe to dump.
    """
    if isinstance(val, str):
        return val.replace("\n", " ").replace("\r", " ")
    if isinstance(val, dict):
        return {k: _safe_str(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_safe_str(item) for item in val]
    return val


def dump_yaml_block(title: str, data: dict[str, Any]) -> str:
    """Serialize data as a Markdown document with a fenced YAML block."""
    data = _safe_str(data)
    yaml_text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return f"# {title}\n\n```yaml\n{yaml_text}```\n"


def write_yaml_block(path: Path, title: str, data: dict[str, Any]) -> None:
    """Atomically write a Markdown YAML protocol document."""
    atomic_write_text(path, dump_yaml_block(title, data))
