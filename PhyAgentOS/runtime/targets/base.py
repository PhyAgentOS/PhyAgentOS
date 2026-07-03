"""Base rollout target definitions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseRolloutTarget(ABC):
    """Contract shared by all runtime rollout targets."""

    @abstractmethod
    def build(self) -> None:
        """Initialize target resources."""

    @abstractmethod
    def describe(self) -> dict[str, Any]:
        """Return target runtime capabilities."""

    @abstractmethod
    def configure_session(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        """Configure the target after preflight acceptance."""

    @abstractmethod
    def start_session(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        """Start target-side session state."""

    @abstractmethod
    def reset(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        """Reset the target for a session and return the initial observation."""

    @abstractmethod
    def observe(self) -> dict[str, Any]:
        """Return the latest target observation."""

    def observe_for_environment(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        """Return a read-only observation for environment/perception refresh."""
        return self.observe()

    @abstractmethod
    def action_chunk(self, executable_action_chunk: dict[str, Any]) -> dict[str, Any]:
        """Apply an executable action chunk and return target execution status."""

    @abstractmethod
    def execution_status(self) -> dict[str, Any]:
        """Return the latest target execution status."""

    def describe_target_tools(self) -> dict[str, Any]:
        """Return target tool metadata for builtin runtimes."""
        return {"tools": []}

    def call_target_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call an exposed target tool."""
        raise NotImplementedError(f"target tool is not implemented: {tool_name}")

    def run_benchmark(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run a target-native benchmark loop."""
        raise NotImplementedError("target benchmark is not implemented")

    @abstractmethod
    def cancel(self, reason: str) -> None:
        """Cancel target-side execution."""

    @abstractmethod
    def close(self) -> None:
        """Release target resources."""
