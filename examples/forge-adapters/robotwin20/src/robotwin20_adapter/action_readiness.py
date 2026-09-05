"""Read-only Action admission gate backed by reviewed readiness evidence.

The gate is intentionally adapter-owned: it consumes an immutable manifest and
manual-review record, but it never starts a planner, simulator, Dora flow, or
hardware command.  Action endpoints call it before allocating an invocation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class ActionReadinessConfigurationError(ValueError):
    """Readiness manifest or review record is not safe to use for admission."""


_MANIFEST_SCHEMA = "paos-robotwin20-readiness-evidence-manifest/v2"
_EVIDENCE_SCHEMA = "paos-robotwin20-readiness-evidence/v1"
_REVIEW_SCHEMA = "paos-robotwin20-readiness-manual-review/v2"
_REVIEW_DECISION = "approved_readiness_evidence_for_next_no_motion_gate"
_CHECKS = ("kinematic", "collision", "workspace")
_ROUTE_CHECKS = (
    "attached_object_collision",
    "complete_transport_descent_retreat",
    "contact_dynamics",
    "workspace_and_joint_limits",
    "stop_control",
)
ACTION_READINESS_PROFILE_SCHEMA_VERSION = "paos-robotwin20-action-readiness/v1"
_VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ActionReadinessConfigurationError(f"cannot read JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ActionReadinessConfigurationError(f"JSON artifact must be an object: {path}")
    return value


def _artifact_path(root: Path, artifact_ref: str) -> Path:
    prefix = "artifact://"
    if not isinstance(artifact_ref, str) or not artifact_ref.startswith(prefix):
        raise ActionReadinessConfigurationError("readiness artifact_ref is invalid")
    parts = artifact_ref.removeprefix(prefix).split("/")
    if len(parts) < 2 or any(not part or part in {".", ".."} for part in parts):
        raise ActionReadinessConfigurationError("readiness artifact_ref path is unsafe")
    path = (root.joinpath(*parts)).with_suffix(".json")
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ActionReadinessConfigurationError("readiness artifact escapes artifact root")
    return resolved


def _require_identity(item: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return all(item.get(key) == value for key, value in expected.items())


def _expand(value: Any, environ: Mapping[str, str]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActionReadinessConfigurationError("action readiness path must be a non-empty string")

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in environ or not environ[name]:
            raise ActionReadinessConfigurationError(f"action readiness variable is unset: {name}")
        return environ[name]

    return _VARIABLE.sub(replace, value)


def _safe_path(raw: str, *, kind: str, directory: bool = False) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ActionReadinessConfigurationError(f"action readiness {kind} must be an absolute path")
    if candidate.is_symlink():
        raise ActionReadinessConfigurationError(f"action readiness {kind} must not be a symlink")
    resolved = candidate.resolve()
    if directory:
        valid = resolved.is_dir()
    else:
        valid = resolved.is_file()
    if not valid:
        suffix = "directory" if directory else "regular file"
        raise ActionReadinessConfigurationError(f"action readiness {kind} must be a {suffix}")
    return resolved


@dataclass(frozen=True)
class ReadinessEvidenceGate:
    """Validate reviewed, same-scene readiness before an Action provider call."""

    manifest_path: Path
    review_path: Path
    artifact_root: Path
    _candidate_evidence: Mapping[str, Mapping[str, Any]]
    _identity: Mapping[str, Any]
    require_complete_route: bool = False

    @classmethod
    def from_files(
        cls,
        manifest_path: str | Path,
        review_path: str | Path,
        *,
        artifact_root: str | Path | None = None,
        require_complete_route: bool = False,
    ) -> "ReadinessEvidenceGate":
        manifest_input = Path(manifest_path).expanduser()
        review_input = Path(review_path).expanduser()
        if manifest_input.is_symlink() or review_input.is_symlink():
            raise ActionReadinessConfigurationError("readiness manifest/review must not be symlinks")
        manifest_file = manifest_input.resolve()
        review_file = review_input.resolve()
        manifest = _read_json(manifest_file)
        review = _read_json(review_file)
        if manifest.get("schema_version") != _MANIFEST_SCHEMA:
            raise ActionReadinessConfigurationError("unsupported readiness manifest schema")
        if manifest.get("motion_authorized") is not False:
            raise ActionReadinessConfigurationError("readiness manifest must be no-motion")
        if review.get("schema_version") != _REVIEW_SCHEMA:
            raise ActionReadinessConfigurationError("unsupported readiness review schema")
        if review.get("decision") != _REVIEW_DECISION:
            raise ActionReadinessConfigurationError("readiness evidence is not manually approved")
        summary = review.get("summary")
        if (
            not isinstance(summary, Mapping)
            or summary.get("motion_authorized_false") is not True
            or summary.get("all_checks_pass") is not True
            or summary.get("binding_match") is not True
            or summary.get("identity_bound") is not True
        ):
            raise ActionReadinessConfigurationError("readiness review does not confirm no-motion")
        digest = hashlib.sha256(manifest_file.read_bytes()).hexdigest()
        if summary.get("manifest_sha256") != digest:
            raise ActionReadinessConfigurationError("readiness manifest digest does not match review")
        identity = manifest.get("request_identity") or review.get("request_identity")
        if not isinstance(identity, Mapping):
            raise ActionReadinessConfigurationError("readiness request identity is missing")
        required_identity = (
            "observation_ref", "scene_revision", "frame_id", "calibration_ref", "candidate_set_ref"
        )
        if any(not isinstance(identity.get(key), str) or not identity[key] for key in required_identity):
            raise ActionReadinessConfigurationError("readiness request identity is incomplete")
        if artifact_root is None:
            root = manifest_file.parent
        else:
            root_input = Path(artifact_root).expanduser()
            if root_input.is_symlink() or not root_input.is_dir():
                raise ActionReadinessConfigurationError("readiness artifact_root must be a directory")
            root = root_input.resolve()
        entries = manifest.get("artifacts")
        if not isinstance(entries, list) or not entries:
            raise ActionReadinessConfigurationError("readiness manifest has no evidence artifacts")
        candidate_evidence: dict[str, Mapping[str, Any]] = {}
        manifest_worker_id = manifest.get("worker_id")
        manifest_binding = manifest.get("embodiment_binding")
        if not isinstance(manifest_worker_id, str) or not manifest_worker_id.strip():
            raise ActionReadinessConfigurationError("readiness manifest worker_id is missing")
        if not isinstance(manifest_binding, Mapping) or not manifest_binding:
            raise ActionReadinessConfigurationError("readiness manifest embodiment binding is missing")
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ActionReadinessConfigurationError("readiness manifest entry is invalid")
            candidate_ref = entry.get("candidate_ref")
            artifact_ref = entry.get("artifact_ref")
            if not isinstance(candidate_ref, str) or not isinstance(artifact_ref, str):
                raise ActionReadinessConfigurationError("readiness manifest entry lacks identity")
            evidence_path = _artifact_path(root, artifact_ref)
            try:
                raw_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            except OSError as exc:
                raise ActionReadinessConfigurationError("readiness evidence artifact is unavailable") from exc
            if entry.get("sha256") != raw_digest:
                raise ActionReadinessConfigurationError("readiness evidence digest mismatch")
            if not _require_identity(
                entry,
                {key: identity[key] for key in required_identity if key != "candidate_set_ref"},
            ) or entry.get("candidate_set_ref") != identity["candidate_set_ref"]:
                raise ActionReadinessConfigurationError("readiness manifest identity mismatch")
            evidence = _read_json(evidence_path)
            if evidence.get("schema_version") != _EVIDENCE_SCHEMA:
                raise ActionReadinessConfigurationError("unsupported readiness evidence schema")
            if evidence.get("motion_authorized") is not False:
                raise ActionReadinessConfigurationError("readiness evidence must be no-motion")
            if evidence.get("worker_id") != manifest_worker_id:
                raise ActionReadinessConfigurationError("readiness evidence worker identity mismatch")
            if evidence.get("embodiment_binding") != manifest_binding:
                raise ActionReadinessConfigurationError("readiness evidence embodiment mismatch")
            checks = evidence.get("checks")
            if not isinstance(checks, Mapping):
                raise ActionReadinessConfigurationError("readiness evidence checks are invalid")
            required_checks = _ROUTE_CHECKS if require_complete_route else _CHECKS
            if set(checks) != set(required_checks) or any(
                checks.get(key) != "pass" for key in required_checks
            ):
                label = "complete-route readiness" if require_complete_route else "readiness"
                raise ActionReadinessConfigurationError(f"{label} evidence checks are not all pass")
            if not _require_identity(evidence, {key: identity[key] for key in required_identity if key != "candidate_set_ref"}):
                raise ActionReadinessConfigurationError("readiness evidence identity mismatch")
            if evidence.get("candidate_set_ref") != identity["candidate_set_ref"]:
                raise ActionReadinessConfigurationError("readiness evidence candidate-set mismatch")
            if evidence.get("candidate_ref") != candidate_ref:
                raise ActionReadinessConfigurationError("readiness manifest/evidence candidate mismatch")
            if candidate_ref in candidate_evidence:
                raise ActionReadinessConfigurationError("duplicate readiness candidate evidence")
            candidate_evidence[candidate_ref] = evidence
        return cls(manifest_file, review_file, root, candidate_evidence, dict(identity), require_complete_route)

    @property
    def candidate_refs(self) -> frozenset[str]:
        return frozenset(self._candidate_evidence)

    def check(self, request: dict[str, Any]) -> str | None:
        """Return a stable rejection code, or ``None`` when admission may proceed."""

        if not isinstance(request, dict):
            return "invalid_arguments"
        for key in (
            "observation_ref", "scene_revision", "frame_id", "calibration_ref", "candidate_set_ref",
        ):
            if request.get(key) != self._identity.get(key):
                return "readiness_identity_mismatch"
        if request.get("freshness_ms", 0) > request.get("max_age_ms", 0):
            return "stale_observation"
        candidate_ref = request.get("candidate_ref")
        evidence = self._candidate_evidence.get(candidate_ref)
        if evidence is None:
            return "readiness_evidence_missing"
        if request.get("entity_ref") != evidence.get("entity_ref"):
            return "readiness_entity_mismatch"
        if evidence.get("motion_authorized") is not False:
            return "readiness_motion_authorized"
        return None


def load_action_readiness_profile(
    path: str | Path, *, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Load the external, profile-owned Action readiness configuration."""
    profile_path = Path(path).expanduser().resolve()
    if not profile_path.is_file() or profile_path.is_symlink():
        raise ActionReadinessConfigurationError("action readiness profile must be a regular file")
    try:
        import yaml
    except ImportError as exc:
        raise ActionReadinessConfigurationError("PyYAML is required to load action readiness profiles") from exc
    try:
        value = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ActionReadinessConfigurationError("action readiness profile could not be loaded") from exc
    if not isinstance(value, dict):
        raise ActionReadinessConfigurationError("action readiness profile must contain an object")
    required = {"schema_version", "manifest", "manual_review", "artifact_root"}
    if set(value) != required or value.get("schema_version") != ACTION_READINESS_PROFILE_SCHEMA_VERSION:
        raise ActionReadinessConfigurationError("action readiness profile fields are invalid")
    variables = dict(os.environ if environ is None else environ)
    expanded = {key: _expand(value[key], variables) for key in required - {"schema_version"}}
    paths = {
        "manifest": _safe_path(expanded["manifest"], kind="manifest"),
        "manual_review": _safe_path(expanded["manual_review"], kind="manual_review"),
        "artifact_root": _safe_path(expanded["artifact_root"], kind="artifact_root", directory=True),
    }
    return {"schema_version": value["schema_version"], **paths}


def build_action_readiness_gate(
    profile_path: str | Path, *, environ: Mapping[str, str] | None = None,
    require_complete_route: bool = False,
) -> ReadinessEvidenceGate:
    profile = load_action_readiness_profile(profile_path, environ=environ)
    return ReadinessEvidenceGate.from_files(
        profile["manifest"], profile["manual_review"], artifact_root=profile["artifact_root"],
        require_complete_route=require_complete_route,
    )


def build_complete_route_readiness_gate(
    profile_path: str | Path, *, environ: Mapping[str, str] | None = None
) -> ReadinessEvidenceGate:
    """Build the fail-closed gate required before physical acquire/place admission."""
    return build_action_readiness_gate(
        profile_path, environ=environ, require_complete_route=True
    )


__all__ = [
    "ACTION_READINESS_PROFILE_SCHEMA_VERSION",
    "ActionReadinessConfigurationError",
    "ReadinessEvidenceGate",
    "build_action_readiness_gate",
    "build_complete_route_readiness_gate",
    "load_action_readiness_profile",
]
