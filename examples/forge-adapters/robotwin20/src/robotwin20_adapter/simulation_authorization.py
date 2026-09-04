"""Strict, declarative authorization profile for future simulation motion.

This module deliberately stops at configuration validation.  Loading a profile
does not start a worker, call RoboTwin, allocate a Gateway invocation, or grant
motion to an Action provider.  A future executor must consume the returned
profile only after its own Gateway admission and reconciliation checks.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .perception_profile import PerceptionProfileError, _worker_config

SIMULATION_AUTHORIZATION_PROFILE_SCHEMA_VERSION = "paos-robotwin20-simulation-motion/v1"
SIMULATION_APPROVAL_SCHEMA_VERSION = "paos-robotwin20-simulation-motion-approval/v1"
SIMULATION_EVIDENCE_MANIFEST_SCHEMA_VERSION = "paos-robotwin20-simulation-motion-evidence/v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ENV = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
_REQUIRED_SCOPES = frozenset(
    {
        "attached_object_collision",
        "complete_transport_descent_retreat",
        "contact_dynamics",
        "after_snapshot_semantic_verification",
    }
)


class SimulationAuthorizationError(ValueError):
    """A simulation-motion profile or approval record is unsafe or incomplete."""


@dataclass(frozen=True)
class SimulationMotionAuthorizationProfile:
    """Validated declaration; this object is not an execution capability."""

    profile_id: str
    profile_sha256: str
    task_name: str
    seed: int
    scene_revision: str
    embodiment_binding: Mapping[str, str]
    runtime_profile: Path
    runtime_profile_sha256: str
    authorization_state: str
    motion_authorized: bool
    approval_record: Path | None
    approval_record_sha256: str | None
    evidence_manifest: Path | None
    evidence_manifest_sha256: str | None
    required_evidence_scopes: tuple[str, ...]
    worker_config: Any
    max_duration_s: float
    cancel_timeout_s: float
    hard_stop_timeout_s: float
    unknown_policy: str
    snapshot_artifact_root: Path
    before_snapshot_required: bool
    after_snapshot_required: bool
    semantic_verifier_required: bool


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - optional adapter dependency
        raise SimulationAuthorizationError("PyYAML is required to load simulation profiles") from exc
    class _UniqueKeyLoader(yaml.SafeLoader):
        pass

    def _mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False):
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise SimulationAuthorizationError("simulation profile contains duplicate YAML keys")
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    _UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        _mapping,
    )
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise SimulationAuthorizationError("simulation profile could not be loaded") from exc
    if not isinstance(value, dict):
        raise SimulationAuthorizationError("simulation profile must contain an object")
    return value


def _expand(value: Any, environ: Mapping[str, str]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SimulationAuthorizationError("simulation profile path must be a non-empty string")
    missing = sorted({name for name in _ENV.findall(value) if not environ.get(name)})
    if missing:
        raise SimulationAuthorizationError(f"simulation profile environment variable is unavailable: {missing[0]}")
    return _ENV.sub(lambda match: environ[match.group(1)], value)


def _path(
    value: Any,
    environ: Mapping[str, str],
    label: str,
    *,
    directory: bool = False,
    secure_file: bool = False,
) -> Path:
    candidate = Path(_expand(value, environ)).expanduser()
    if not candidate.is_absolute():
        raise SimulationAuthorizationError(f"{label} must be absolute")
    if candidate.is_symlink():
        raise SimulationAuthorizationError(f"{label} must not be a symlink")
    resolved = candidate.resolve()
    if (resolved.is_dir() if directory else resolved.is_file()) is False:
        kind = "directory" if directory else "regular file"
        raise SimulationAuthorizationError(f"{label} must be an existing {kind}")
    if secure_file and resolved.stat().st_mode & 0o022:
        raise SimulationAuthorizationError(f"{label} must not be group/world writable")
    return resolved


def _digest(path: Path, label: str) -> str:
    try:
        value = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise SimulationAuthorizationError(f"{label} is unavailable") from exc
    return value


def _profile_identity_digest(raw: Mapping[str, Any]) -> str:
    """Digest profile semantics while excluding the approval-record self-reference."""
    normalized = json.loads(json.dumps(raw))
    authorization = normalized.get("authorization")
    if isinstance(authorization, dict):
        authorization["approval_record_sha256"] = None
        authorization["approval_record"] = None
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SimulationAuthorizationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise SimulationAuthorizationError(f"{label} must be boolean")
    return value


def _positive(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise SimulationAuthorizationError(f"{label} must be positive")
    return float(value)


def _validate_approval(
    path: Path,
    expected_digest: str,
    *,
    profile_id: str,
    profile_sha256: str,
    task_name: str,
    scene_revision: str,
    embodiment_binding: Mapping[str, str],
    scopes: tuple[str, ...],
    evidence_manifest_sha256: str,
) -> None:
    if _digest(path, "simulation approval record") != expected_digest:
        raise SimulationAuthorizationError("simulation approval record digest does not match profile")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SimulationAuthorizationError("simulation approval record is invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "decision", "motion_authorized", "profile_id", "profile_sha256",
        "task_name", "scene_revision", "embodiment_binding", "evidence_scopes", "reviewer_id",
        "reviewed_at", "evidence_manifest_sha256",
    }:
        raise SimulationAuthorizationError("simulation approval record fields are invalid")
    if value["schema_version"] != SIMULATION_APPROVAL_SCHEMA_VERSION:
        raise SimulationAuthorizationError("simulation approval schema_version is unsupported")
    if value["decision"] != "approved_simulation_motion":
        raise SimulationAuthorizationError("simulation approval decision is not approved")
    if value["motion_authorized"] is not True:
        raise SimulationAuthorizationError("simulation approval must explicitly authorize motion")
    if value["profile_id"] != profile_id or value["profile_sha256"] != profile_sha256:
        raise SimulationAuthorizationError("simulation approval profile identity mismatch")
    if value["task_name"] != task_name or value["scene_revision"] != scene_revision:
        raise SimulationAuthorizationError("simulation approval task identity mismatch")
    if value["embodiment_binding"] != dict(embodiment_binding):
        raise SimulationAuthorizationError("simulation approval embodiment mismatch")
    if value["evidence_scopes"] != list(scopes):
        raise SimulationAuthorizationError("simulation approval evidence scope mismatch")
    if value["evidence_manifest_sha256"] != evidence_manifest_sha256:
        raise SimulationAuthorizationError("simulation approval evidence manifest mismatch")
    if not isinstance(value["reviewer_id"], str) or not value["reviewer_id"].strip():
        raise SimulationAuthorizationError("simulation approval reviewer_id is missing")
    if not isinstance(value["reviewed_at"], str) or not value["reviewed_at"].strip():
        raise SimulationAuthorizationError("simulation approval reviewed_at must be an ISO timestamp")
    try:
        parsed_at = datetime.fromisoformat(value["reviewed_at"])
    except ValueError as exc:
        raise SimulationAuthorizationError("simulation approval reviewed_at must be an ISO timestamp") from exc
    if parsed_at.tzinfo is None:
        raise SimulationAuthorizationError("simulation approval reviewed_at must include a timezone")


def load_simulation_motion_profile(
    path: str | os.PathLike[str],
    *,
    environ: Mapping[str, str] | None = None,
) -> SimulationMotionAuthorizationProfile:
    """Load and validate a profile without starting any execution component."""

    profile_input = Path(path).expanduser()
    if not profile_input.is_absolute() or not profile_input.is_file() or profile_input.is_symlink():
        raise SimulationAuthorizationError("simulation profile must be an existing absolute regular file")
    profile_path = profile_input.resolve()
    raw = _read_yaml(profile_path)
    required = {"schema_version", "profile_id", "runtime", "scope", "authorization", "execution", "stop", "snapshot"}
    if set(raw) != required:
        raise SimulationAuthorizationError("simulation profile fields are invalid")
    if raw["schema_version"] != SIMULATION_AUTHORIZATION_PROFILE_SCHEMA_VERSION:
        raise SimulationAuthorizationError("simulation profile schema_version is unsupported")
    profile_id = raw["profile_id"]
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise SimulationAuthorizationError("simulation profile_id is missing")
    runtime = raw["runtime"]
    scope = raw["scope"]
    authorization = raw["authorization"]
    execution = raw["execution"]
    stop = raw["stop"]
    snapshot = raw["snapshot"]
    if not all(isinstance(item, Mapping) for item in (runtime, scope, authorization, execution, stop, snapshot)):
        raise SimulationAuthorizationError("simulation profile sections must be objects")
    if set(runtime) != {"profile", "profile_sha256"}:
        raise SimulationAuthorizationError("simulation runtime fields are invalid")
    if set(scope) != {"task_name", "seed", "scene_revision", "embodiment_binding"}:
        raise SimulationAuthorizationError("simulation scope fields are invalid")
    if set(authorization) != {
        "state", "motion_authorized", "approval_record", "approval_record_sha256",
        "evidence_manifest", "evidence_manifest_sha256", "required_evidence_scopes",
    }:
        raise SimulationAuthorizationError("simulation authorization fields are invalid")
    if set(execution) != {"worker", "max_duration_s"}:
        raise SimulationAuthorizationError("simulation execution fields are invalid")
    if set(stop) != {"cancel_timeout_s", "hard_stop_timeout_s", "unknown_policy"}:
        raise SimulationAuthorizationError("simulation stop fields are invalid")
    if set(snapshot) != {"artifact_root", "before_required", "after_required", "semantic_verifier_required"}:
        raise SimulationAuthorizationError("simulation snapshot fields are invalid")
    variables = dict(os.environ if environ is None else environ)
    runtime_profile = _path(runtime["profile"], variables, "runtime.profile")
    runtime_digest = _sha(
        _expand(runtime["profile_sha256"], variables), "runtime.profile_sha256"
    )
    if _digest(runtime_profile, "runtime.profile") != runtime_digest:
        raise SimulationAuthorizationError("runtime profile digest does not match")
    task_name = scope["task_name"]
    scene_revision = scope["scene_revision"]
    if not isinstance(task_name, str) or not task_name.strip() or not isinstance(scene_revision, str) or not scene_revision.strip():
        raise SimulationAuthorizationError("simulation task/scene identity is missing")
    seed = scope["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise SimulationAuthorizationError("simulation seed must be an integer")
    binding = scope["embodiment_binding"]
    if not isinstance(binding, Mapping) or set(binding) != {"robot_identity", "gripper_identity", "embodiment_topology", "planner_profile", "profile_digest"}:
        raise SimulationAuthorizationError("simulation embodiment binding fields are invalid")
    if any(not isinstance(value, str) or not value.strip() for value in binding.values()):
        raise SimulationAuthorizationError("simulation embodiment binding values are invalid")
    binding = {key: _expand(value, variables) for key, value in binding.items()}
    state = authorization["state"]
    if state not in {"disabled", "pending_review", "approved"}:
        raise SimulationAuthorizationError("simulation authorization state is invalid")
    motion_authorized = _bool(authorization["motion_authorized"], "authorization.motion_authorized")
    if motion_authorized is not (state == "approved"):
        raise SimulationAuthorizationError("authorization state and motion_authorized disagree")
    raw_scopes = authorization["required_evidence_scopes"]
    if (
        not isinstance(raw_scopes, list)
        or any(not isinstance(item, str) for item in raw_scopes)
        or set(raw_scopes) != _REQUIRED_SCOPES
        or raw_scopes != sorted(raw_scopes)
    ):
        raise SimulationAuthorizationError("required evidence scopes are incomplete or duplicated")
    scopes = tuple(sorted(raw_scopes))
    approval_record = authorization["approval_record"]
    approval_digest = authorization["approval_record_sha256"]
    evidence_manifest = authorization["evidence_manifest"]
    evidence_manifest_digest = authorization["evidence_manifest_sha256"]
    if state == "approved":
        approval_path = _path(
            approval_record,
            variables,
            "authorization.approval_record",
            secure_file=True,
        )
        approval_hash = _sha(
            _expand(approval_digest, variables), "authorization.approval_record_sha256"
        )
        evidence_path = _path(
            evidence_manifest,
            variables,
            "authorization.evidence_manifest",
            secure_file=True,
        )
        evidence_hash = _sha(
            _expand(evidence_manifest_digest, variables),
            "authorization.evidence_manifest_sha256",
        )
    else:
        if any(
            value is not None
            for value in (approval_record, approval_digest, evidence_manifest, evidence_manifest_digest)
        ):
            raise SimulationAuthorizationError("disabled/pending profile must not carry approval/evidence record")
        approval_path = None
        approval_hash = None
        evidence_path = None
        evidence_hash = None
    if execution["worker"] is None and state != "approved":
        worker_config = None
    else:
        try:
            worker_config = _worker_config(execution["worker"], variables, "simulation.worker")
        except PerceptionProfileError as exc:
            raise SimulationAuthorizationError(str(exc)) from exc
    max_duration = _positive(execution["max_duration_s"], "execution.max_duration_s")
    cancel_timeout = _positive(stop["cancel_timeout_s"], "stop.cancel_timeout_s")
    hard_stop_timeout = _positive(stop["hard_stop_timeout_s"], "stop.hard_stop_timeout_s")
    if hard_stop_timeout < cancel_timeout:
        raise SimulationAuthorizationError("hard_stop_timeout_s must be >= cancel_timeout_s")
    if stop["unknown_policy"] != "halt_and_reconcile":
        raise SimulationAuthorizationError("unknown_policy must be halt_and_reconcile")
    artifact_root = _path(snapshot["artifact_root"], variables, "snapshot.artifact_root", directory=True)
    before_required = _bool(snapshot["before_required"], "snapshot.before_required")
    after_required = _bool(snapshot["after_required"], "snapshot.after_required")
    semantic_required = _bool(snapshot["semantic_verifier_required"], "snapshot.semantic_verifier_required")
    if not (before_required and after_required and semantic_required):
        raise SimulationAuthorizationError("simulation snapshots and semantic verification are mandatory")
    profile_sha256 = _profile_identity_digest(raw)
    if evidence_path is not None and evidence_hash is not None:
        if _digest(evidence_path, "simulation evidence manifest") != evidence_hash:
            raise SimulationAuthorizationError("simulation evidence manifest digest does not match profile")
        try:
            evidence_value = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SimulationAuthorizationError("simulation evidence manifest is invalid JSON") from exc
        if not isinstance(evidence_value, dict) or set(evidence_value) != {
            "schema_version", "profile_id", "task_name", "scene_revision", "embodiment_binding",
            "motion_authorized", "scope_status", "artifacts",
        }:
            raise SimulationAuthorizationError("simulation evidence manifest fields are invalid")
        if evidence_value["schema_version"] != SIMULATION_EVIDENCE_MANIFEST_SCHEMA_VERSION:
            raise SimulationAuthorizationError("simulation evidence manifest schema_version is unsupported")
        if (
            evidence_value["profile_id"] != profile_id
            or evidence_value["task_name"] != task_name
            or evidence_value["scene_revision"] != scene_revision
            or evidence_value["embodiment_binding"] != dict(binding)
            or evidence_value["motion_authorized"] is not False
        ):
            raise SimulationAuthorizationError("simulation evidence manifest identity is invalid")
        statuses = evidence_value["scope_status"]
        if not isinstance(statuses, Mapping) or set(statuses) != _REQUIRED_SCOPES or any(
            statuses.get(scope) != "pass" for scope in _REQUIRED_SCOPES
        ):
            raise SimulationAuthorizationError("simulation evidence scopes are not all pass")
        artifacts = evidence_value["artifacts"]
        if not isinstance(artifacts, list) or not artifacts:
            raise SimulationAuthorizationError("simulation evidence manifest has no artifacts")
        artifact_scopes: set[str] = set()
        for artifact in artifacts:
            if not isinstance(artifact, Mapping) or set(artifact) != {"artifact_ref", "sha256", "scope"}:
                raise SimulationAuthorizationError("simulation evidence artifact is invalid")
            if not isinstance(artifact["artifact_ref"], str) or not artifact["artifact_ref"].strip():
                raise SimulationAuthorizationError("simulation evidence artifact_ref is invalid")
            _sha(artifact["sha256"], "simulation evidence artifact sha256")
            if artifact["scope"] not in _REQUIRED_SCOPES:
                raise SimulationAuthorizationError("simulation evidence artifact scope is invalid")
            artifact_scopes.add(artifact["scope"])
        if artifact_scopes != _REQUIRED_SCOPES:
            raise SimulationAuthorizationError("simulation evidence artifacts do not cover all scopes")
    if approval_path is not None and approval_hash is not None:
        _validate_approval(
            approval_path,
            approval_hash,
            profile_id=profile_id,
            profile_sha256=profile_sha256,
            task_name=task_name,
            scene_revision=scene_revision,
            embodiment_binding=binding,
            scopes=scopes,
            evidence_manifest_sha256=evidence_hash,
        )
    return SimulationMotionAuthorizationProfile(
        profile_id=profile_id,
        profile_sha256=profile_sha256,
        task_name=task_name,
        seed=seed,
        scene_revision=scene_revision,
        embodiment_binding=dict(binding),
        runtime_profile=runtime_profile,
        runtime_profile_sha256=runtime_digest,
        authorization_state=state,
        motion_authorized=motion_authorized,
        approval_record=approval_path,
        approval_record_sha256=approval_hash,
        evidence_manifest=evidence_path,
        evidence_manifest_sha256=evidence_hash,
        required_evidence_scopes=scopes,
        worker_config=worker_config,
        max_duration_s=max_duration,
        cancel_timeout_s=cancel_timeout,
        hard_stop_timeout_s=hard_stop_timeout,
        unknown_policy=stop["unknown_policy"],
        snapshot_artifact_root=artifact_root,
        before_snapshot_required=before_required,
        after_snapshot_required=after_required,
        semantic_verifier_required=semantic_required,
    )


__all__ = [
    "SIMULATION_AUTHORIZATION_PROFILE_SCHEMA_VERSION",
    "SIMULATION_APPROVAL_SCHEMA_VERSION",
    "SIMULATION_EVIDENCE_MANIFEST_SCHEMA_VERSION",
    "SimulationAuthorizationError",
    "SimulationMotionAuthorizationProfile",
    "load_simulation_motion_profile",
]
