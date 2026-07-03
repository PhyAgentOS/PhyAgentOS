"""Runtime RPC envelope schema."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, field_validator


RUNTIME_RPC_VERSION = "phyagentos.runtime_rpc.v2"


class RuntimeEnvelope(BaseModel):
    """Typed envelope shared by target, policy, and runtime RPC messages."""

    ALLOWED_TYPES: ClassVar[set[str]] = {
        "target.hello",
        "target.describe",
        "target.configure_session",
        "target.start_session",
        "target.reset",
        "target.observe",
        "target.observation",
        "target.action_chunk",
        "target.benchmark",
        "target.execution_status",
        "target.heartbeat",
        "target.cancel",
        "target.stop_session",
        "target.close",
        "agent_tool.describe",
        "agent_tool.call",
        "agent_tool.result",
        "agent_loop.status",
        "agent_loop.close",
        "policy.hello",
        "policy.describe",
        "policy.infer",
        "policy.infer_result",
        "policy.heartbeat",
        "runtime.preflight_request",
        "runtime.preflight_result",
        "runtime.runner_started",
        "runtime.runner_heartbeat",
        "runtime.runner_result",
        "runtime.error",
    }

    version: Literal["phyagentos.runtime_rpc.v2"] = RUNTIME_RPC_VERSION
    type: str
    session_id: str | None = None
    target_id: str | None = None
    skillruntime_id: str | None = None
    episode_id: str | None = None
    seq: int = Field(ge=0)
    timestamp_ns: int = Field(ge=0)
    trace_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in cls.ALLOWED_TYPES:
            raise ValueError(f"unsupported runtime RPC type: {value}")
        return value
