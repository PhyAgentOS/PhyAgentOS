"""Atomic persistent state for explicitly managed Skill runtimes."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from PhyAgentOS.config.paths import get_skill_runtime_state_dir

STATE_VERSION = 1
RuntimeStatus = Literal["starting", "running", "stopping", "stopped", "failed"]
_STATUSES = {"starting", "running", "stopping", "stopped", "failed"}
_FIELDS = {
    "state_version",
    "skill_name",
    "profile",
    "status",
    "flow_name",
    "gateway_url",
    "started_at",
    "updated_at",
    "last_error",
    "active_invocations",
}


class StateError(ValueError):
    """Raised when persisted runtime state is malformed."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class RuntimeState:
    """Last known lifecycle state for one installed Skill."""

    skill_name: str
    profile: str
    status: RuntimeStatus
    flow_name: str
    gateway_url: str
    started_at: str | None = None
    updated_at: str = field(default_factory=utc_now)
    last_error: str | None = None
    active_invocations: tuple[str, ...] = ()
    state_version: int = STATE_VERSION

    @classmethod
    def from_dict(cls, value: Any) -> RuntimeState:
        if not isinstance(value, dict):
            raise StateError("runtime state must be a JSON object")
        unknown = sorted(set(value) - _FIELDS)
        if unknown:
            raise StateError(f"runtime state has unknown field(s): {', '.join(unknown)}")
        if value.get("state_version") != STATE_VERSION:
            raise StateError(f"state_version must be {STATE_VERSION}")
        required = ("skill_name", "profile", "status", "flow_name", "gateway_url", "updated_at")
        for name in required:
            if not isinstance(value.get(name), str) or not value[name]:
                raise StateError(f"{name} must be a non-empty string")
        if value["status"] not in _STATUSES:
            raise StateError(f"invalid runtime status: {value['status']}")
        invocations = value.get("active_invocations", [])
        if not isinstance(invocations, list) or not all(
            isinstance(item, str) and item for item in invocations
        ):
            raise StateError("active_invocations must be a list of non-empty strings")
        for optional in ("started_at", "last_error"):
            if value.get(optional) is not None and not isinstance(value[optional], str):
                raise StateError(f"{optional} must be a string or null")
        return cls(
            skill_name=value["skill_name"],
            profile=value["profile"],
            status=value["status"],
            flow_name=value["flow_name"],
            gateway_url=value["gateway_url"],
            started_at=value.get("started_at"),
            updated_at=value["updated_at"],
            last_error=value.get("last_error"),
            active_invocations=tuple(invocations),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["active_invocations"] = list(self.active_invocations)
        return value

    def with_status(
        self,
        status: RuntimeStatus,
        *,
        error: str | None = None,
        active_invocations: tuple[str, ...] | None = None,
    ) -> RuntimeState:
        return RuntimeState(
            skill_name=self.skill_name,
            profile=self.profile,
            status=status,
            flow_name=self.flow_name,
            gateway_url=self.gateway_url,
            started_at=self.started_at,
            last_error=error,
            active_invocations=(
                self.active_invocations if active_invocations is None else active_invocations
            ),
        )


class RuntimeStateStore:
    """Read and atomically replace per-Skill JSON state files."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or get_skill_runtime_state_dir()).expanduser()

    def path_for(self, skill_name: str) -> Path:
        if skill_name in {"", ".", ".."} or "/" in skill_name or "\\" in skill_name:
            raise StateError("invalid Skill name for runtime state")
        return self.root / f"{skill_name}.json"

    def load(self, skill_name: str) -> RuntimeState | None:
        path = self.path_for(skill_name)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise StateError("cannot read runtime state") from exc
        except json.JSONDecodeError as exc:
            raise StateError("runtime state is not valid JSON") from exc
        state = RuntimeState.from_dict(value)
        if state.skill_name != skill_name:
            raise StateError("runtime state Skill name does not match its filename")
        return state

    def save(self, state: RuntimeState) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.path_for(state.skill_name)
        payload = json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n"
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise
        return target
