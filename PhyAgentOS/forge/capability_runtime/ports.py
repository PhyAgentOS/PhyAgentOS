"""Provider-port protocols for the simulator-neutral Forge capability runtime.

The protocols intentionally describe data boundaries only.  Implementations may
live in RoboTwin, a replay source, or a hardware process, but the PAOS runtime
never imports those providers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class ActionAdmission:
    """Provider result retained by the generic invocation owner."""

    pending_polls: int = 0
    terminal_result: Mapping[str, Any] = field(default_factory=dict)


class ObservationSource(Protocol):
    """Capture measured sensor artifacts; no simulator truth is implied."""

    def capture(self, request: Mapping[str, Any]) -> Mapping[str, Any] | None: ...


class SceneUnderstandingProvider(Protocol):
    """Infer entity/relation claims from observation artifacts."""

    def understand(self, request: Mapping[str, Any]) -> Mapping[str, Any] | None: ...


class GraspProposalProvider(Protocol):
    """Generate provider-neutral grasp proposals without action admission."""

    def propose(self, request: Mapping[str, Any]) -> Mapping[str, Any] | None: ...


class ReadinessEvaluator(Protocol):
    """Evaluate workspace/kinematic/collision readiness without motion."""

    def evaluate(self, request: Mapping[str, Any]) -> Mapping[str, Any] | None: ...


class ManipulationExecutor(Protocol):
    """Admit bounded physical effects through the Gateway-owned Action lifecycle."""

    def acquire(self, request: Mapping[str, Any]) -> ActionAdmission | None: ...

    def place(self, request: Mapping[str, Any]) -> ActionAdmission | None: ...


class EnvironmentAdapter(Protocol):
    """Environment lifecycle seam; provider-specific fields stay behind it."""

    def reset(self, *, seed: int | None = None) -> None: ...

    def snapshot(self) -> Mapping[str, Any]: ...


class QueryEndpoint(Protocol):
    """Generic synchronous Query operation."""

    def invoke(self, arguments: Any) -> Mapping[str, Any]: ...


class ActionEndpoint(Protocol):
    """Generic bounded Action admission operation."""

    def admit(self, arguments: Any) -> ActionAdmission: ...


__all__ = [
    "ActionAdmission",
    "ActionEndpoint",
    "EnvironmentAdapter",
    "GraspProposalProvider",
    "ManipulationExecutor",
    "ObservationSource",
    "QueryEndpoint",
    "ReadinessEvaluator",
    "SceneUnderstandingProvider",
]
