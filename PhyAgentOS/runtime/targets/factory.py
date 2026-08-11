"""Build runtime targets from target registry specs."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

from PhyAgentOS.runtime.communication.target_ws_client import TargetWSClient
from PhyAgentOS.runtime.errors import TargetBuildError
from PhyAgentOS.runtime.schemas import TargetSpec
from PhyAgentOS.runtime.targets.base import BaseRolloutTarget
from PhyAgentOS.runtime.targets.local.dummy_sim_target import DummySimTarget
from PhyAgentOS.runtime.targets.remote.behavior1k.proxy import Behavior1KRemoteTargetProxy
from PhyAgentOS.runtime.targets.remote.isaacsim.proxy import IsaacSimRemoteTargetProxy
from PhyAgentOS.runtime.targets.remote.libero.proxy import LiberoRemoteTargetProxy
from PhyAgentOS.runtime.targets.remote.proxy import RemoteTargetProxy

LocalTargetFactory = Callable[[TargetSpec], BaseRolloutTarget]
RemoteTargetFactory = Callable[[TargetSpec, TargetWSClient], BaseRolloutTarget]

_LOCAL_TARGET_FACTORIES: dict[str, LocalTargetFactory] = {}
_REMOTE_TARGET_FACTORIES: dict[str, RemoteTargetFactory] = {}


def register_local_target_runtime(runtime_name: str, factory: LocalTargetFactory) -> None:
    _LOCAL_TARGET_FACTORIES[runtime_name] = factory


def register_remote_target_runtime(runtime_name: str, factory: RemoteTargetFactory) -> None:
    _REMOTE_TARGET_FACTORIES[runtime_name] = factory


def build_target(target: TargetSpec, *, target_endpoint: str | None = None) -> BaseRolloutTarget:
    endpoint = target_endpoint or target.runtime.target_endpoint
    if target.target_class == "local":
        return build_local_target(target)
    if target.target_class == "remote":
        if not endpoint:
            raise TargetBuildError(f"remote target {target.id} does not define target_endpoint")
        if not _is_targetws_endpoint(endpoint):
            raise TargetBuildError(f"unsupported remote target endpoint for {target.id}: {endpoint}")
        return build_remote_target(target, endpoint)
    raise TargetBuildError(f"unsupported target_class for {target.id}: {target.target_class}")


def build_local_target(target: TargetSpec) -> BaseRolloutTarget:
    factory = _LOCAL_TARGET_FACTORIES.get(target.runtime.target_runtime)
    if factory is None:
        raise TargetBuildError(f"unsupported local target runtime: {target.runtime.target_runtime}")
    return factory(target)


def build_remote_target(target: TargetSpec, endpoint: str) -> BaseRolloutTarget:
    factory = _REMOTE_TARGET_FACTORIES.get(target.runtime.target_runtime)
    if factory is None:
        raise TargetBuildError(f"unsupported remote target runtime: {target.runtime.target_runtime}")
    client = TargetWSClient(
        endpoint,
        target_id=target.id,
        timeout_s=float(target.config.get("target_ws_timeout_s", 300)),
    )
    return factory(target, client)


def build_dummy_sim_target(target: TargetSpec) -> DummySimTarget:
    return DummySimTarget(target.config)


def build_remote_target_proxy(target: TargetSpec, client: TargetWSClient) -> RemoteTargetProxy:
    return RemoteTargetProxy(client, config=target.config)


def build_go2_remote_target_proxy(target: TargetSpec, client: TargetWSClient) -> RemoteTargetProxy:
    return RemoteTargetProxy(client, config=target.config)


def build_libero_remote_target_proxy(target: TargetSpec, client: TargetWSClient) -> LiberoRemoteTargetProxy:
    return LiberoRemoteTargetProxy(client, config=target.config)


def _is_targetws_endpoint(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    return parsed.scheme == "targetws"


def build_isaacsim_remote_target_proxy(target: TargetSpec, client: TargetWSClient) -> IsaacSimRemoteTargetProxy:
    return IsaacSimRemoteTargetProxy(client, config=target.config)


def build_behavior1k_remote_target_proxy(target: TargetSpec, client: TargetWSClient) -> Behavior1KRemoteTargetProxy:
    return Behavior1KRemoteTargetProxy(client, config=target.config)


register_local_target_runtime("DummySimTargetRuntime", build_dummy_sim_target)
register_remote_target_runtime("RemoteTargetProxy", build_remote_target_proxy)
register_remote_target_runtime("Go2RemoteTargetProxy", build_go2_remote_target_proxy)
register_remote_target_runtime("LiberoRemoteTargetProxy", build_libero_remote_target_proxy)
register_remote_target_runtime("IsaacSimRemoteTargetProxy", build_isaacsim_remote_target_proxy)
register_remote_target_runtime("Behavior1KRemoteTargetProxy", build_behavior1k_remote_target_proxy)
