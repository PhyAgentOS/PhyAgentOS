"""Build runtime adapters and action bridges from lightweight registries."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PhyAgentOS.runtime.adapters.behavior1k.target_adapter import Behavior1kTargetAdapter
from PhyAgentOS.runtime.adapters.bridges import SafetyClampBridge
from PhyAgentOS.runtime.adapters.go2.target_adapter import Go2BuiltinTargetAdapter
from PhyAgentOS.runtime.adapters.isaacsim.target_adapter import IsaacSimTargetAdapter
from PhyAgentOS.runtime.adapters.libero.target_adapter import LiberoTargetAdapter
from PhyAgentOS.runtime.adapters.openpi.b1k_dummy_policy_adapter import Behavior1kDummyPolicyAdapter
from PhyAgentOS.runtime.adapters.openpi.b1k_openpi_policy_adapter import (
    Behavior1kOpenPIPolicyAdapter,
)
from PhyAgentOS.runtime.adapters.openpi.dummy_openpi_adapter import DummyOpenPIAdapter
from PhyAgentOS.runtime.adapters.openpi.pi05_policy_adapter import OpenPIPi05Adapter
from PhyAgentOS.runtime.adapters.openpi.pipergo2_isaac_policy_adapter import (
    PiperGo2IsaacPolicyAdapter,
)
from PhyAgentOS.runtime.adapters.target_dummy import DummySimTargetAdapter
from PhyAgentOS.runtime.errors import AdapterError
from PhyAgentOS.runtime.schemas.adapter_plan import AdapterPlan

AdapterFactory = Callable[[], Any]

_TARGET_ADAPTER_FACTORIES: dict[str, AdapterFactory] = {}
_POLICY_ADAPTER_FACTORIES: dict[str, AdapterFactory] = {}
_ACTION_BRIDGE_FACTORIES: dict[str, AdapterFactory] = {}


def register_target_adapter(adapter_id: str, factory: AdapterFactory) -> None:
    _TARGET_ADAPTER_FACTORIES[_require_uri(adapter_id, "target_adapter://")] = factory


def register_policy_adapter(adapter_id: str, factory: AdapterFactory) -> None:
    _POLICY_ADAPTER_FACTORIES[_require_uri(adapter_id, "policy_adapter://")] = factory


def register_action_bridge(bridge_id: str, factory: AdapterFactory) -> None:
    _ACTION_BRIDGE_FACTORIES[_require_uri(bridge_id, "bridge://")] = factory


def build_target_adapter(adapter_id: str):
    normalized = _require_uri(adapter_id, "target_adapter://")
    factory = _TARGET_ADAPTER_FACTORIES.get(normalized)
    if factory is not None:
        return factory()
    raise AdapterError(f"unsupported target adapter: {adapter_id}")


def build_policy_adapter(adapter_id: str | None):
    if adapter_id is None:
        return None
    normalized = _require_uri(adapter_id, "policy_adapter://")
    factory = _POLICY_ADAPTER_FACTORIES.get(normalized)
    if factory is not None:
        return factory()
    raise AdapterError(f"unsupported policy adapter: {adapter_id}")


def build_action_bridge(bridge_id: str):
    normalized = _require_uri(bridge_id, "bridge://")
    factory = _ACTION_BRIDGE_FACTORIES.get(normalized)
    if factory is not None:
        return factory()
    raise AdapterError(f"unsupported action bridge: {bridge_id}")


def build_adapter_stack(plan: AdapterPlan):
    return (
        build_target_adapter(plan.target_adapter),
        build_policy_adapter(plan.policy_adapter),
        [build_action_bridge(bridge_id) for bridge_id in plan.action_bridges],
    )


def _require_uri(value: str, prefix: str) -> str:
    if not value.startswith(prefix):
        raise AdapterError(f"expected {prefix} URI, got: {value}")
    return value[len(prefix) :]


register_target_adapter("target_adapter://dummy_sim_adapter", DummySimTargetAdapter)
register_target_adapter("target_adapter://libero_adapter", LiberoTargetAdapter)
register_target_adapter("target_adapter://libero_mock_adapter", LiberoTargetAdapter)
register_target_adapter("target_adapter://isaacsim_adapter", IsaacSimTargetAdapter)
register_target_adapter("target_adapter://behavior1k_openpi_adapter", Behavior1kTargetAdapter)
register_target_adapter("target_adapter://go2_builtin_adapter", Go2BuiltinTargetAdapter)
register_policy_adapter("policy_adapter://dummy_openpi_adapter", DummyOpenPIAdapter)
register_policy_adapter("policy_adapter://b1k_dummy_policy_adapter", Behavior1kDummyPolicyAdapter)
register_policy_adapter("policy_adapter://b1k_openpi_policy_adapter", Behavior1kOpenPIPolicyAdapter)
register_policy_adapter("policy_adapter://openpi_pi05_adapter", OpenPIPi05Adapter)
register_policy_adapter("policy_adapter://pipergo2_isaac_openpi_adapter", PiperGo2IsaacPolicyAdapter)
register_action_bridge("bridge://safety_clamp", SafetyClampBridge)
