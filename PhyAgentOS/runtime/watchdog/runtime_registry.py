"""Runtime registries for target and skill factories."""

from __future__ import annotations

from collections.abc import Callable

from PhyAgentOS.runtime.schemas import TargetSpec
from PhyAgentOS.runtime.skillruntime.base import BaseSkillRuntime
from PhyAgentOS.runtime.skillruntime.builtin.command_sim import CommandSimSkillRuntime
from PhyAgentOS.runtime.skillruntime.builtin.libero_benchmark import LiberoBenchmarkSkillRuntime
from PhyAgentOS.runtime.skillruntime.policy import OpenPISkillRuntime
from PhyAgentOS.runtime.communication.target_ws_client import TargetWSClient
from PhyAgentOS.runtime.targets.base import BaseRolloutTarget
from PhyAgentOS.runtime.targets.factory import (
    build_target,
    register_local_target_runtime,
    register_remote_target_runtime,
)
from PhyAgentOS.runtime.watchdog.errors import SchemaValidationError


SkillFactory = Callable[[], BaseSkillRuntime]
LocalTargetFactory = Callable[[TargetSpec], BaseRolloutTarget]
RemoteTargetFactory = Callable[[TargetSpec, TargetWSClient], BaseRolloutTarget]


_SKILL_FACTORIES: dict[str, SkillFactory] = {}


def register_target_runtime(runtime_name: str, factory: LocalTargetFactory) -> None:
    register_local_target_runtime(runtime_name, factory)


def register_remote_target(runtime_name: str, factory: RemoteTargetFactory) -> None:
    register_remote_target_runtime(runtime_name, factory)


def register_skill_runtime(name: str, factory: SkillFactory) -> None:
    _SKILL_FACTORIES[name] = factory


class TargetRuntimeRegistry:
    """Build local or remote targets from target runtime specs."""

    def build(self, target_spec: TargetSpec, *, target_endpoint: str | None = None):
        return build_target(target_spec, target_endpoint=target_endpoint)


class SkillRuntimeRegistry:
    """Map skill runtime names to skill runtime factories."""

    def __init__(self):
        self._factories = _SKILL_FACTORIES

    def build(self, runtime_name: str) -> BaseSkillRuntime:
        factory = self._factories.get(runtime_name)
        if factory is None:
            raise SchemaValidationError(f"unsupported skill runtime: {runtime_name}")
        return factory()


register_skill_runtime("OpenPISkillRuntime", OpenPISkillRuntime)
register_skill_runtime("CommandSimSkillRuntime", CommandSimSkillRuntime)
register_skill_runtime("LiberoBenchmarkSkillRuntime", LiberoBenchmarkSkillRuntime)
