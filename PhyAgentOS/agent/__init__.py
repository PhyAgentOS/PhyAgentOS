"""Agent core module with lazy exports for isolated Agent services."""

from importlib import import_module

__all__ = ["AgentLoop", "ContextBuilder", "MemoryStore", "SkillsLoader"]

_EXPORTS = {
    "AgentLoop": ("PhyAgentOS.agent.loop", "AgentLoop"),
    "ContextBuilder": ("PhyAgentOS.agent.context", "ContextBuilder"),
    "MemoryStore": ("PhyAgentOS.agent.memory", "MemoryStore"),
    "SkillsLoader": ("PhyAgentOS.agent.skills", "SkillsLoader"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attribute = _EXPORTS[name]
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
