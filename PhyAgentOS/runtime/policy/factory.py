"""Policy client factory and endpoint parsing."""

from __future__ import annotations

from urllib.parse import urlparse

from PhyAgentOS.runtime.errors import PolicyConnectionError
from PhyAgentOS.runtime.policy.b1k_websocket_client import Behavior1kWebsocketPolicyClient
from PhyAgentOS.runtime.policy.base_client import BasePolicyClient
from PhyAgentOS.runtime.policy.dummy_client import DummyPolicyClient
from PhyAgentOS.runtime.policy.openpi.client import OpenPIClientPolicyWrapper


def parse_policy_endpoint(endpoint: str) -> tuple[str, str, int]:
    parsed = urlparse(endpoint)
    if parsed.scheme == "dummy" and parsed.netloc == "local":
        return ("dummy", "local", 0)
    if parsed.scheme == "openpi" and parsed.hostname and parsed.port:
        return ("openpi", parsed.hostname, int(parsed.port))
    if parsed.scheme in ("b1k-ws", "b1kws") and parsed.hostname and parsed.port:
        return ("b1k-ws", parsed.hostname, int(parsed.port))
    if parsed.scheme == "policyws" and parsed.hostname and parsed.port:
        return ("policyws", parsed.hostname, int(parsed.port))
    raise PolicyConnectionError(f"unsupported policy endpoint: {endpoint}")


def build_policy_client(
    endpoint: str,
    *,
    timeout_s: float = 5.0,
    action_dim: int = 7,
    chunk_size: int = 4,
) -> BasePolicyClient:
    kind, host, port = parse_policy_endpoint(endpoint)
    if kind == "dummy":
        return DummyPolicyClient(action_dim=action_dim, chunk_size=chunk_size)
    if kind in {"openpi", "policyws"}:
        return OpenPIClientPolicyWrapper(host=host, port=port, timeout_s=timeout_s)
    if kind == "b1k-ws":
        return Behavior1kWebsocketPolicyClient(host=host, port=port, timeout_s=timeout_s)
    raise PolicyConnectionError(f"unsupported policy endpoint kind: {kind}")
