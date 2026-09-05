"""Tool registry for dynamic tool management."""

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from PhyAgentOS.agent.tools.base import Tool


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._execution_guard: Callable[[str, dict[str, Any]], str | None | Awaitable[str | None]] | None = None

    def set_execution_guard(
        self,
        guard: Callable[[str, dict[str, Any]], str | None | Awaitable[str | None]] | None,
    ) -> None:
        """Install an optional pre-execution guard owned by the caller.

        The registry does not interpret the guard result or persist anything;
        this keeps planning/admission orthogonal to Tool transport.
        """
        self._execution_guard = guard

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions in OpenAI format."""
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """Execute a tool by name with given parameters."""
        hint = "\n\n[Analyze the error above and try a different approach.]"

        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"

        try:
            if self._execution_guard is not None:
                guard_result = self._execution_guard(name, params)
                if inspect.isawaitable(guard_result):
                    guard_result = await guard_result
                if guard_result is not None:
                    return guard_result
            # Attempt to cast parameters to match schema types
            params = tool.cast_params(params)

            # Validate parameters
            errors = tool.validate_params(params)
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + hint
            result = await tool.execute(**params)
            if isinstance(result, str) and result.startswith("Error"):
                return result + hint
            return result
        except Exception as e:
            return f"Error executing {name}: {str(e)}" + hint

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
