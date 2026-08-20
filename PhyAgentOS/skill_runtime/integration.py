"""Bridge explicitly started Skill runtimes into the PAOS Agent process."""

from __future__ import annotations

from collections.abc import Iterator, MutableSet
from dataclasses import dataclass

from PhyAgentOS.forge.tool_client import ForgeToolClient
from PhyAgentOS.skill_runtime.catalog import SkillCatalog
from PhyAgentOS.skill_runtime.manager import RuntimeManager
from PhyAgentOS.skill_runtime.state import RuntimeStateStore


@dataclass(frozen=True)
class ActiveSkillRuntime:
    """One healthy runtime selected for Agent Tool registration."""

    skill_name: str
    gateway_url: str
    client: ForgeToolClient
    invocation_ids: MutableSet[str]


class PersistentInvocationSet(MutableSet[str]):
    """Persist Action identities so runtime shutdown can enforce reconciliation."""

    def __init__(self, skill_name: str, store: RuntimeStateStore) -> None:
        self.skill_name = skill_name
        self.store = store

    def _items(self) -> set[str]:
        state = self.store.load(self.skill_name)
        return set(state.active_invocations if state is not None else ())

    def __contains__(self, value: object) -> bool:
        return value in self._items()

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._items()))

    def __len__(self) -> int:
        return len(self._items())

    def add(self, value: str) -> None:
        state = self.store.load(self.skill_name)
        if state is None:
            raise RuntimeError("Skill runtime state disappeared while starting an Action")
        items = set(state.active_invocations)
        items.add(value)
        self.store.save(
            state.with_status(
                state.status,
                error=state.last_error,
                active_invocations=tuple(sorted(items)),
            )
        )

    def discard(self, value: str) -> None:
        state = self.store.load(self.skill_name)
        if state is None or value not in state.active_invocations:
            return
        items = set(state.active_invocations)
        items.discard(value)
        self.store.save(
            state.with_status(
                state.status,
                error=state.last_error,
                active_invocations=tuple(sorted(items)),
            )
        )


def discover_active_runtime(
    *,
    catalog: SkillCatalog | None = None,
    state_store: RuntimeStateStore | None = None,
    manager: RuntimeManager | None = None,
) -> ActiveSkillRuntime | None:
    """Return the single healthy explicitly started runtime, if one exists."""
    catalog = catalog or SkillCatalog()
    state_store = state_store or RuntimeStateStore()
    manager = manager or RuntimeManager(catalog=catalog, state_store=state_store)
    active = []
    for manifest in catalog.list():
        try:
            report = manager.status(manifest.name)
        except Exception:
            continue
        if report.ready and report.state is not None:
            active.append((manifest, report.state))
    if not active:
        return None
    if len(active) > 1:
        names = ", ".join(sorted(manifest.name for manifest, _ in active))
        raise RuntimeError(
            f"Multiple Skill runtimes are active ({names}); stop all but one before starting PAOS"
        )
    manifest, _ = active[0]
    return ActiveSkillRuntime(
        skill_name=manifest.name,
        gateway_url=manifest.gateway_url,
        client=ForgeToolClient(manifest.gateway_url),
        invocation_ids=PersistentInvocationSet(manifest.name, state_store),
    )


__all__ = [
    "ActiveSkillRuntime",
    "PersistentInvocationSet",
    "discover_active_runtime",
]
