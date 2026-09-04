"""Strict profile and client boundary for an authorized RoboTwin simulation probe.

Loading a profile only validates configuration.  Simulation world changes occur
only when :meth:`SimulationProbeClient.probe` starts the separately configured
worker and submits a request covered by the external approval record.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Mapping

from .perception_profile import PerceptionProfileError, _absolute_path, _expand, _worker_config
from .process_worker import JsonlProcessWorkerClient
from .route_readiness import route_geometry_digest, validate_route_request

SIMULATION_PROBE_PROFILE_SCHEMA_VERSION = "paos-robotwin20-simulation-probe-profile/v1"
SIMULATION_PROBE_RESPONSE_SCHEMA_VERSION = "paos-robotwin20-simulation-probe/v1"


class SimulationProbeProfileError(ValueError):
    """The simulation-probe deployment profile is incomplete or unsafe."""


class SimulationProbeClient:
    """Profile-owned bounded client for the external simulation-only producer."""

    def __init__(
        self,
        client: JsonlProcessWorkerClient,
        *,
        worker_id: str,
        producer_binding: Mapping[str, str],
    ) -> None:
        self.client = client
        self.worker_id = worker_id
        self.producer_binding = dict(producer_binding)

    def probe(self, request: Mapping[str, Any], *, candidate_ref: str) -> Mapping[str, Any]:
        validate_route_request(request)
        if not isinstance(candidate_ref, str) or candidate_ref not in {
            item["candidate_ref"] for item in request["candidates"]
        }:
            raise SimulationProbeProfileError("simulation probe candidate is not in request")
        response = self.client.request(
            {
                "request_id": request["request_id"],
                "route_request": dict(request),
                "candidate_ref": candidate_ref,
                "calibration_ref": request["calibration_ref"],
            }
        )
        if response.get("request_id") != request["request_id"]:
            raise SimulationProbeProfileError("simulation probe response identity mismatch")
        if response.get("schema_version") != SIMULATION_PROBE_RESPONSE_SCHEMA_VERSION:
            raise SimulationProbeProfileError("simulation probe response schema mismatch")
        if response.get("worker_id") != self.worker_id:
            raise SimulationProbeProfileError("simulation probe worker identity mismatch")
        if response.get("producer_binding") != self.producer_binding:
            raise SimulationProbeProfileError("simulation probe producer identity mismatch")
        status = response.get("status")
        if status == "available":
            if (
                response.get("motion_authorized") is not True
                or response.get("provider_available") is not True
                or response.get("world_change_started") is not True
                or response.get("world_change_completed") is not True
                or response.get("reconciliation_required") is not False
            ):
                raise SimulationProbeProfileError("simulation probe success state is inconsistent")
            external = response.get("external_evidence")
            if (
                not isinstance(external, Mapping)
                or external.get("request_id") != request["request_id"]
                or external.get("candidate_ref") != candidate_ref
                or external.get("route_geometry_digest") != route_geometry_digest(request)
                or external.get("producer_binding") != self.producer_binding
            ):
                raise SimulationProbeProfileError("simulation probe evidence binding is invalid")
        elif status == "unavailable":
            if response.get("provider_available") is not True:
                raise SimulationProbeProfileError("simulation probe runtime availability is inconsistent")
            started = response.get("world_change_started")
            completed = response.get("world_change_completed")
            reconciliation_required = response.get("reconciliation_required")
            motion_authorized = response.get("motion_authorized")
            if (
                not isinstance(motion_authorized, bool)
                or not isinstance(started, bool)
                or completed is not False
                or (started and not motion_authorized)
            ):
                raise SimulationProbeProfileError("simulation probe failure state is inconsistent")
            if not isinstance(reconciliation_required, bool):
                raise SimulationProbeProfileError("simulation probe reconciliation state is inconsistent")
            if not started and reconciliation_required:
                raise SimulationProbeProfileError("simulation probe reconciliation state is inconsistent")
            failure = response.get("failure_evidence")
            if started and (
                not isinstance(failure, Mapping)
                or set(failure) != {"artifact_ref", "sha256"}
            ):
                raise SimulationProbeProfileError("simulation probe failure evidence is missing")
        else:
            raise SimulationProbeProfileError("simulation probe response status is invalid")
        return dict(response)

    def release(self) -> None:
        self.client.release()


def load_simulation_probe_profile(path: str | os.PathLike[str]) -> dict[str, Any]:
    profile_path = Path(path).expanduser()
    if not profile_path.is_absolute() or not profile_path.is_file() or profile_path.is_symlink():
        raise SimulationProbeProfileError(
            "simulation probe profile must be an existing absolute regular file"
        )
    try:
        import yaml
    except ImportError as exc:
        raise SimulationProbeProfileError("PyYAML is required to load simulation probe profiles") from exc
    class _UniqueKeyLoader(yaml.SafeLoader):
        pass

    def _mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False):
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise SimulationProbeProfileError("simulation probe profile contains duplicate YAML keys")
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    _UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)
    try:
        value = yaml.load(profile_path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise SimulationProbeProfileError("simulation probe profile could not be loaded") from exc
    if not isinstance(value, dict):
        raise SimulationProbeProfileError("simulation probe profile must contain an object")
    value["_profile_path"] = str(profile_path.resolve())
    value["_profile_sha256"] = hashlib.sha256(profile_path.read_bytes()).hexdigest()
    return value


def _control_path(value: Any, variables: Mapping[str, str], artifact_root: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise SimulationProbeProfileError("simulation probe stop_file must be a path string")
    try:
        candidate = Path(_expand(value, variables)).expanduser()
    except PerceptionProfileError as exc:
        raise SimulationProbeProfileError(str(exc)) from exc
    if not candidate.is_absolute() or candidate.is_symlink():
        raise SimulationProbeProfileError("simulation probe stop_file must be an absolute non-symlink path")
    resolved = candidate.resolve()
    root = artifact_root.resolve()
    if root not in resolved.parents or not resolved.parent.is_dir():
        raise SimulationProbeProfileError("simulation probe stop_file must be below artifact_root")
    return resolved


def build_simulation_probe_client(
    profile: Mapping[str, Any], *, environ: Mapping[str, str] | None = None
) -> SimulationProbeClient:
    metadata = {"_profile_path", "_profile_sha256"}
    required = {
        "schema_version",
        "worker_id",
        "producer_id",
        "producer_profile_sha256",
        "runtime_root",
        "runtime_profile",
        "artifact_root",
        "approval_ref",
        "max_duration_s",
        "stop_file",
        "worker",
    }
    if not isinstance(profile, Mapping) or set(profile) - metadata != required:
        raise SimulationProbeProfileError("simulation probe profile fields are invalid")
    if profile["schema_version"] != SIMULATION_PROBE_PROFILE_SCHEMA_VERSION:
        raise SimulationProbeProfileError("simulation probe profile schema_version is unsupported")
    variables = dict(os.environ if environ is None else environ)
    try:
        worker_id = _expand(profile["worker_id"], variables)
        producer_id = _expand(profile["producer_id"], variables)
        configured_digest = _expand(profile["producer_profile_sha256"], variables)
        runtime_root = _absolute_path(
            profile["runtime_root"], variables, "simulation probe runtime_root", must_be_directory=True
        )
        runtime_profile = _absolute_path(
            profile["runtime_profile"], variables, "simulation probe runtime_profile", must_be_file=True
        )
        artifact_root = _absolute_path(
            profile["artifact_root"], variables, "simulation probe artifact_root", must_be_directory=True
        )
        approval_ref = _expand(profile["approval_ref"], variables)
        worker_config = _worker_config(profile["worker"], variables, "simulation probe worker")
    except (KeyError, TypeError, PerceptionProfileError) as exc:
        raise SimulationProbeProfileError(str(exc)) from exc
    if not worker_id.strip() or not producer_id.strip():
        raise SimulationProbeProfileError("simulation probe worker/producer identity is invalid")
    actual_digest = profile.get("_profile_sha256")
    if not isinstance(actual_digest, str):
        raise SimulationProbeProfileError("simulation probe profile must be loaded from a file")
    if configured_digest != actual_digest:
        raise SimulationProbeProfileError("simulation probe profile digest binding is invalid")
    if not approval_ref.startswith("artifact://"):
        raise SimulationProbeProfileError("simulation probe approval_ref is invalid")
    max_duration = profile["max_duration_s"]
    if isinstance(max_duration, bool) or not isinstance(max_duration, (int, float)) or max_duration <= 0:
        raise SimulationProbeProfileError("simulation probe max_duration_s must be positive")
    stop_file = _control_path(profile["stop_file"], variables, artifact_root)
    command = worker_config.command
    bindings = (
        ("--runtime-root", str(runtime_root)),
        ("--runtime-profile", str(runtime_profile)),
        ("--artifact-root", str(artifact_root)),
        ("--worker-id", worker_id),
        ("--producer-id", producer_id),
        ("--producer-profile-sha256", configured_digest),
        ("--approval-ref", approval_ref),
        ("--max-duration-s", str(max_duration)),
        ("--stop-file", str(stop_file)),
    )
    for flag, expected in bindings:
        try:
            index = command.index(flag)
        except ValueError as exc:
            raise SimulationProbeProfileError(f"simulation probe worker must bind {flag}") from exc
        if index + 1 >= len(command) or command[index + 1] != expected:
            raise SimulationProbeProfileError(f"simulation probe worker binding is invalid: {flag}")
    producer_binding = {
        "producer_id": producer_id,
        "profile_sha256": configured_digest,
        "evidence_mode": "independent_simulation_probe",
    }
    return SimulationProbeClient(
        JsonlProcessWorkerClient(worker_config),
        worker_id=worker_id,
        producer_binding=producer_binding,
    )


__all__ = [
    "SIMULATION_PROBE_PROFILE_SCHEMA_VERSION",
    "SIMULATION_PROBE_RESPONSE_SCHEMA_VERSION",
    "SimulationProbeClient",
    "SimulationProbeProfileError",
    "build_simulation_probe_client",
    "load_simulation_probe_profile",
]
