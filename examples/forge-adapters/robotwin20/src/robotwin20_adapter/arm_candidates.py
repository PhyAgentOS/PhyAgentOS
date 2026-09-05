"""RoboTwin arm enumeration and complete-route selection without motion."""

from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any, Protocol

from PhyAgentOS.forge.manipulation import (
    CoordinationMode,
    ManipulationIntent,
    ReplanCoordinator,
    ReplanSignal,
    RouteFailure,
)

from .route_readiness import (
    ROUTE_CHECKS,
    ROUTE_PHASES,
    route_geometry_digest,
    validate_route_request,
)

ARM_PLANNING_PROFILE_SCHEMA_VERSION = "paos-robotwin20-arm-planning/v1"
ROUTE_EVALUATION_SCHEMA_VERSION = "paos-robotwin20-route-evaluation/v1"
ROUTE_SELECTION_SCHEMA_VERSION = "paos-robotwin20-route-selection/v1"
_OUTCOME_STATUSES = frozenset({"pass", "fail", "unavailable"})
_OWNERS = frozenset(
    {"input", "binding", "planner", "policy", "collision", "readiness", "infrastructure"}
)


class ArmPlanningError(ValueError):
    """An arm profile, route option, or selector result is unsafe or malformed."""


class RouteReadinessProvider(Protocol):
    """Evaluate one complete candidate/arm route without changing the world."""

    def evaluate(
        self,
        request: Mapping[str, Any],
        option: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


def _identity(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ArmPlanningError(f"{label} is invalid")
    normalized = value.strip()
    if not normalized or normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise ArmPlanningError(f"{label} is invalid")
    return normalized


def load_arm_planning_profile(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load an immutable-shape deployment profile for arm enumeration."""

    profile_path = Path(path).expanduser()
    if not profile_path.is_absolute() or not profile_path.is_file() or profile_path.is_symlink():
        raise ArmPlanningError("arm planning profile must be an absolute regular file")
    try:
        import yaml
    except ImportError as exc:
        raise ArmPlanningError("PyYAML is required to load arm planning profiles") from exc
    try:
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ArmPlanningError("arm planning profile could not be loaded") from exc
    validate_arm_planning_profile(profile)
    return dict(profile)


def validate_arm_planning_profile(profile: Any) -> None:
    """Validate embodiment-owned arm and deterministic scoring configuration."""

    if not isinstance(profile, Mapping) or set(profile) != {
        "schema_version",
        "embodiment_id",
        "topology",
        "arms",
        "selection_policy",
    }:
        raise ArmPlanningError("arm planning profile fields are invalid")
    if profile["schema_version"] != ARM_PLANNING_PROFILE_SCHEMA_VERSION:
        raise ArmPlanningError("arm planning profile schema_version is unsupported")
    _identity(profile["embodiment_id"], "embodiment_id")
    if profile["topology"] not in {"single_arm", "dual_independent", "dual_coordinated"}:
        raise ArmPlanningError("arm planning topology is unsupported")
    arms = profile["arms"]
    if not isinstance(arms, list) or not arms:
        raise ArmPlanningError("arm planning profile requires arms")
    arm_ids: list[str] = []
    for arm in arms:
        if not isinstance(arm, Mapping) or set(arm) != {
            "arm_id",
            "planner_profile_ref",
            "workspace_ref",
            "joint_limits_ref",
        }:
            raise ArmPlanningError("arm planning arm fields are invalid")
        arm_ids.append(_identity(arm["arm_id"], "arm_id"))
        for field in ("planner_profile_ref", "workspace_ref", "joint_limits_ref"):
            value = arm[field]
            if not isinstance(value, str) or not value.startswith("artifact://"):
                raise ArmPlanningError(f"arm planning {field} is invalid")
    if len(arm_ids) != len(set(arm_ids)):
        raise ArmPlanningError("arm planning arm identities must be unique")
    expected_arm_count = 1 if profile["topology"] == "single_arm" else 2
    if len(arm_ids) != expected_arm_count:
        raise ArmPlanningError("arm planning topology does not match configured arms")
    policy = profile["selection_policy"]
    if not isinstance(policy, Mapping) or set(policy) != {
        "max_options",
        "weights",
        "tie_break",
    }:
        raise ArmPlanningError("selection policy fields are invalid")
    if not isinstance(policy["max_options"], int) or not 1 <= policy["max_options"] <= 1024:
        raise ArmPlanningError("selection policy max_options is invalid")
    weights = policy["weights"]
    if not isinstance(weights, Mapping) or set(weights) != {
        "route_length",
        "speed_margin",
    }:
        raise ArmPlanningError("selection policy weights are invalid")
    for value in weights.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ArmPlanningError("selection policy weights must be finite and non-negative")
    if not any(float(value) > 0 for value in weights.values()):
        raise ArmPlanningError("selection policy requires a positive weight")
    if policy["tie_break"] != "candidate_ref_then_arm_id":
        raise ArmPlanningError("selection policy tie_break is unsupported")


def enumerate_arm_candidates(
    intent: ManipulationIntent,
    candidates: Sequence[Mapping[str, Any]],
    profile: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Expand grasp candidates over allowed arms without planner or simulator calls."""

    if not isinstance(intent, ManipulationIntent):
        raise TypeError("arm enumeration requires a ManipulationIntent")
    validate_arm_planning_profile(profile)
    if not isinstance(candidates, Sequence) or not candidates:
        raise ArmPlanningError("arm enumeration requires candidates")
    configured = {item["arm_id"]: dict(item) for item in profile["arms"]}
    if not set(intent.allowed_arms) <= configured.keys():
        raise ArmPlanningError("intent allowed_arms are not present in the embodiment profile")
    if intent.coordination_mode is CoordinationMode.BIMANUAL and profile["topology"] != "dual_coordinated":
        raise ArmPlanningError("embodiment profile does not authorize bimanual coordination")
    if intent.coordination_mode is CoordinationMode.BIMANUAL:
        raise ArmPlanningError(
            "bimanual enumeration requires a synchronized two-arm route provider"
        )

    seen: set[str] = set()
    options: list[dict[str, Any]] = []
    arm_groups = tuple((arm_id,) for arm_id in intent.allowed_arms)
    max_options = profile["selection_policy"]["max_options"]
    if len(candidates) * len(arm_groups) > max_options:
        raise ArmPlanningError("arm candidate enumeration exceeds configured max_options")
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ArmPlanningError("arm candidate must be an object")
        candidate_ref = candidate.get("candidate_ref")
        entity_ref = candidate.get("entity_ref")
        if (
            not isinstance(candidate_ref, str)
            or not candidate_ref.startswith("candidate://")
            or candidate_ref in seen
            or entity_ref != intent.entity_ref
        ):
            raise ArmPlanningError("arm candidate identity is invalid or unbound")
        seen.add(candidate_ref)
        if candidate.get("candidate_set_ref", intent.candidate_set_ref) != intent.candidate_set_ref:
            raise ArmPlanningError("arm candidate-set binding is invalid")
        if candidate.get("observation_ref", intent.observation_ref) != intent.observation_ref:
            raise ArmPlanningError("arm candidate observation binding is invalid")
        if candidate.get("scene_revision", intent.scene_revision) != intent.scene_revision:
            raise ArmPlanningError("arm candidate scene revision is stale")
        if candidate.get("frame_id", intent.frame_id) != intent.frame_id:
            raise ArmPlanningError("arm candidate frame binding is invalid")
        if candidate.get("calibration_ref", intent.calibration_ref) != intent.calibration_ref:
            raise ArmPlanningError("arm candidate calibration binding is invalid")
        for arm_ids in arm_groups:
            option = {
                "option_id": hashlib.sha256(
                    f"{intent.task_id}\n{intent.revision_id}\n{intent.node_id}\n{candidate_ref}\n{','.join(arm_ids)}".encode()
                ).hexdigest()[:24],
                "candidate_ref": candidate_ref,
                "entity_ref": entity_ref,
                "task_id": intent.task_id,
                "revision_id": intent.revision_id,
                "node_id": intent.node_id,
                "node_digest": intent.node_digest,
                "arm_ids": list(arm_ids),
                "candidate": deepcopy(dict(candidate)),
                "arm_profiles": [deepcopy(configured[arm_id]) for arm_id in arm_ids],
                "observation_ref": intent.observation_ref,
                "candidate_set_ref": intent.candidate_set_ref,
                "scene_revision": intent.scene_revision,
                "frame_id": intent.frame_id,
                "calibration_ref": intent.calibration_ref,
                "motion_authorized": False,
                "world_change_started": False,
            }
            options.append(option)
    return tuple(options)


def _route_length(candidate: Mapping[str, Any]) -> float:
    route = candidate["route"]
    positions = [waypoint["position_m"] for phase in route for waypoint in phase["waypoints"]]
    return sum(
        math.dist(previous, current)
        for previous, current in zip(positions, positions[1:])
    )


class CompleteRouteSelector:
    """Evaluate and rank complete routes; never start motion or create an invocation."""

    def __init__(
        self,
        evaluator: RouteReadinessProvider
        | Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
        profile: Mapping[str, Any],
    ) -> None:
        if not callable(getattr(evaluator, "evaluate", None)) and not callable(evaluator):
            raise TypeError("route selector evaluator must expose evaluate(request) or be callable")
        validate_arm_planning_profile(profile)
        self.evaluator = evaluator
        self.profile = deepcopy(dict(profile))

    def select(
        self,
        intent: ManipulationIntent,
        base_request: Mapping[str, Any],
        options: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any] | ReplanSignal:
        if not isinstance(intent, ManipulationIntent):
            raise TypeError("route selection requires a ManipulationIntent")
        self._validate_base_request(intent, base_request)
        if not isinstance(options, Sequence) or not options:
            return ReplanCoordinator().build_signal(
                intent,
                (),
                reason="candidate_set_invalid",
                next_actions=("regenerate_candidates",),
            )
        if len(options) > self.profile["selection_policy"]["max_options"]:
            raise ArmPlanningError("route options exceed configured max_options")
        weights = self.profile["selection_policy"]["weights"]
        accepted: list[tuple[float, str, str, dict[str, Any]]] = []
        failures: list[RouteFailure] = []
        seen_options: set[str] = set()
        seen_routes: set[tuple[str, tuple[str, ...]]] = set()
        for option in options:
            option_id, arm_ids, candidate = self._validate_option(intent, option, seen_options)
            route_identity = (candidate["candidate_ref"], arm_ids)
            if route_identity in seen_routes:
                raise ArmPlanningError("route option candidate/arm identity is duplicated")
            seen_routes.add(route_identity)
            request = deepcopy(dict(base_request))
            request["request_id"] = f"{base_request['request_id']}-{option_id}"
            request["candidates"] = [deepcopy(candidate)]
            validate_route_request(request)
            evaluate = getattr(self.evaluator, "evaluate", None)
            try:
                raw = (
                    evaluate(deepcopy(request), deepcopy(option))
                    if callable(evaluate)
                    else self.evaluator(deepcopy(request), deepcopy(option))
                )
            except Exception as exc:
                failures.append(
                    RouteFailure(
                        candidate_ref=candidate["candidate_ref"],
                        arm_ids=arm_ids,
                        phase="none",
                        code="readiness_provider_error",
                        owner="infrastructure",
                        detail=f"route readiness provider raised {type(exc).__name__}",
                        route_digest=route_geometry_digest(request),
                    )
                )
                continue
            try:
                normalized = self._validate_result(request, option, raw)
            except ArmPlanningError as exc:
                failures.append(
                    RouteFailure(
                        candidate_ref=candidate["candidate_ref"],
                        arm_ids=arm_ids,
                        phase="none",
                        code="invalid_readiness_result",
                        owner="readiness",
                        detail=str(exc),
                        route_digest=route_geometry_digest(request),
                    )
                )
                continue
            if normalized["status"] != "pass":
                failures.append(
                    RouteFailure(
                        candidate_ref=candidate["candidate_ref"],
                        arm_ids=arm_ids,
                        phase=normalized["phase"],
                        code=normalized["code"],
                        owner=normalized["owner"],
                        detail=normalized["detail"],
                        route_digest=normalized["route_geometry_digest"],
                    )
                )
                continue
            score = (
                -float(weights["route_length"]) * normalized["metrics"]["route_length_m"]
                + float(weights["speed_margin"])
                * normalized["metrics"]["min_joint_speed_margin_radps"]
            )
            accepted.append((score, candidate["candidate_ref"], ",".join(arm_ids), normalized))
        if not accepted:
            return ReplanCoordinator(max_failures=self.profile["selection_policy"]["max_options"]).build_signal(
                intent,
                failures,
            )
        accepted.sort(key=lambda item: (-item[0], item[1], item[2]))
        score, _candidate_ref, _arm_key, selected = accepted[0]
        return {
            "schema_version": ROUTE_SELECTION_SCHEMA_VERSION,
            "status": "selected",
            "task_id": intent.task_id,
            "revision_id": intent.revision_id,
            "node_id": intent.node_id,
            "node_digest": intent.node_digest,
            "entity_ref": intent.entity_ref,
            "observation_ref": intent.observation_ref,
            "scene_revision": intent.scene_revision,
            "frame_id": intent.frame_id,
            "calibration_ref": intent.calibration_ref,
            "candidate_set_ref": intent.candidate_set_ref,
            "selected_option_id": selected["option_id"],
            "candidate_ref": selected["candidate_ref"],
            "arm_ids": list(selected["arm_ids"]),
            "route_geometry_digest": selected["route_geometry_digest"],
            "evidence_refs": list(selected["evidence_refs"]),
            "score": score,
            "rejected_routes": [item.model_dump(mode="json") for item in failures],
            "motion_authorized": False,
            "world_change_started": False,
        }

    @staticmethod
    def _validate_base_request(
        intent: ManipulationIntent,
        request: Mapping[str, Any],
    ) -> None:
        if not isinstance(request, Mapping):
            raise ArmPlanningError("route base request must be an object")
        bindings = {
            "observation_ref": intent.observation_ref,
            "scene_revision": intent.scene_revision,
            "frame_id": intent.frame_id,
            "calibration_ref": intent.calibration_ref,
            "candidate_set_ref": intent.candidate_set_ref,
        }
        if any(request.get(key) != value for key, value in bindings.items()):
            raise ArmPlanningError("route base request does not match manipulation intent")
        if not isinstance(request.get("request_id"), str) or not request["request_id"].strip():
            raise ArmPlanningError("route base request_id is invalid")

    def _validate_option(
        self,
        intent: ManipulationIntent,
        option: Mapping[str, Any],
        seen: set[str],
    ) -> tuple[str, tuple[str, ...], dict[str, Any]]:
        if not isinstance(option, Mapping) or set(option) != {
            "option_id",
            "candidate_ref",
            "entity_ref",
            "task_id",
            "revision_id",
            "node_id",
            "node_digest",
            "arm_ids",
            "candidate",
            "arm_profiles",
            "observation_ref",
            "candidate_set_ref",
            "scene_revision",
            "frame_id",
            "calibration_ref",
            "motion_authorized",
            "world_change_started",
        }:
            raise ArmPlanningError("route option fields are invalid")
        option_id = _identity(option["option_id"], "option_id")
        if option_id in seen:
            raise ArmPlanningError("route option identity is duplicated")
        seen.add(option_id)
        arm_ids = tuple(option["arm_ids"]) if isinstance(option["arm_ids"], list) else ()
        if (
            not arm_ids
            or any(not isinstance(arm_id, str) for arm_id in arm_ids)
            or len(arm_ids) != len(set(arm_ids))
            or not set(arm_ids) <= set(intent.allowed_arms)
        ):
            raise ArmPlanningError("route option arm binding is invalid")
        configured = {item["arm_id"]: dict(item) for item in self.profile["arms"]}
        if option["arm_profiles"] != [configured[arm_id] for arm_id in arm_ids]:
            raise ArmPlanningError("route option arm profile binding is invalid")
        candidate = option["candidate"]
        if (
            not isinstance(candidate, Mapping)
            or option["candidate_ref"] != candidate.get("candidate_ref")
            or option["entity_ref"] != candidate.get("entity_ref")
            or option["entity_ref"] != intent.entity_ref
            or option["task_id"] != intent.task_id
            or option["revision_id"] != intent.revision_id
            or option["node_id"] != intent.node_id
            or option["node_digest"] != intent.node_digest
            or option["observation_ref"] != intent.observation_ref
            or option["candidate_set_ref"] != intent.candidate_set_ref
            or option["scene_revision"] != intent.scene_revision
            or option["frame_id"] != intent.frame_id
            or option["calibration_ref"] != intent.calibration_ref
            or option["motion_authorized"] is not False
            or option["world_change_started"] is not False
        ):
            raise ArmPlanningError("route option identity or no-motion binding is invalid")
        return option_id, arm_ids, dict(candidate)

    @staticmethod
    def _validate_result(
        request: Mapping[str, Any],
        option: Mapping[str, Any],
        raw: Any,
    ) -> dict[str, Any]:
        required = {
            "schema_version",
            "request_id",
            "task_id",
            "revision_id",
            "node_id",
            "node_digest",
            "candidate_ref",
            "entity_ref",
            "observation_ref",
            "scene_revision",
            "frame_id",
            "calibration_ref",
            "candidate_set_ref",
            "arm_ids",
            "option_id",
            "status",
            "checks",
            "phase",
            "code",
            "owner",
            "detail",
            "route_geometry_digest",
            "evidence_refs",
            "motion_authorized",
            "world_change_started",
            "metrics",
        }
        if not isinstance(raw, Mapping) or set(raw) != required:
            raise ArmPlanningError("route evaluator result fields are invalid")
        if raw["schema_version"] != ROUTE_EVALUATION_SCHEMA_VERSION or raw["request_id"] != request["request_id"]:
            raise ArmPlanningError("route evaluator result identity is invalid")
        candidate = request["candidates"][0]
        if (
            raw["task_id"] != option["task_id"]
            or raw["revision_id"] != option["revision_id"]
            or raw["node_id"] != option["node_id"]
            or raw["node_digest"] != option["node_digest"]
            or raw["candidate_ref"] != candidate["candidate_ref"]
            or raw["entity_ref"] != candidate["entity_ref"]
            or raw["observation_ref"] != option["observation_ref"]
            or raw["scene_revision"] != option["scene_revision"]
            or raw["frame_id"] != option["frame_id"]
            or raw["calibration_ref"] != option["calibration_ref"]
            or raw["candidate_set_ref"] != option["candidate_set_ref"]
            or raw["option_id"] != option["option_id"]
            or raw["arm_ids"] != option["arm_ids"]
        ):
            raise ArmPlanningError("route evaluator option binding is invalid")
        if raw["status"] not in _OUTCOME_STATUSES:
            raise ArmPlanningError("route evaluator status is invalid")
        checks = raw["checks"]
        if not isinstance(checks, Mapping) or set(checks) != set(ROUTE_CHECKS):
            raise ArmPlanningError("route evaluator checks are invalid")
        if any(value not in _OUTCOME_STATUSES for value in checks.values()):
            raise ArmPlanningError("route evaluator check status is invalid")
        if raw["status"] == "pass" and any(value != "pass" for value in checks.values()):
            raise ArmPlanningError("passing route evaluator result has non-passing checks")
        if raw["status"] != "pass" and all(value == "pass" for value in checks.values()):
            raise ArmPlanningError("non-passing route evaluator result requires a failed check")
        for key in ("phase", "code", "detail"):
            if not isinstance(raw[key], str) or not raw[key].strip():
                raise ArmPlanningError(f"route evaluator {key} is invalid")
        if raw["owner"] not in _OWNERS:
            raise ArmPlanningError("route evaluator failure owner is invalid")
        if raw["phase"] not in {*ROUTE_PHASES, "none"}:
            raise ArmPlanningError("route evaluator phase is invalid")
        if raw["status"] == "pass" and (
            raw["phase"] != "none" or raw["code"] != "ok" or raw["owner"] != "readiness"
        ):
            raise ArmPlanningError("passing route evaluator result has invalid outcome fields")
        if raw["motion_authorized"] is not False or raw["world_change_started"] is not False:
            raise ArmPlanningError("route evaluator result must remain no-motion")
        if raw["route_geometry_digest"] != route_geometry_digest(request):
            raise ArmPlanningError("route evaluator geometry digest is invalid")
        metrics = raw["metrics"]
        if not isinstance(metrics, Mapping) or set(metrics) != {
            "route_length_m",
            "min_joint_speed_margin_radps",
        }:
            raise ArmPlanningError("route evaluator metrics are invalid")
        for value in metrics.values():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ArmPlanningError("route evaluator metrics must be finite and non-negative")
        if abs(float(metrics["route_length_m"]) - _route_length(candidate)) > 1e-6:
            raise ArmPlanningError("route evaluator route-length metric is invalid")
        refs = raw["evidence_refs"]
        if not isinstance(refs, list) or not refs or any(
            not isinstance(ref, str) or not ref.startswith("artifact://") for ref in refs
        ):
            raise ArmPlanningError("route evaluator evidence_refs are invalid")
        if len(refs) != len(set(refs)):
            raise ArmPlanningError("route evaluator evidence_refs are duplicated")
        normalized = dict(raw)
        normalized["arm_ids"] = tuple(raw["arm_ids"])
        normalized["metrics"] = {
            key: float(value) for key, value in metrics.items()
        }
        return normalized


__all__ = [
    "ARM_PLANNING_PROFILE_SCHEMA_VERSION",
    "ROUTE_EVALUATION_SCHEMA_VERSION",
    "ROUTE_SELECTION_SCHEMA_VERSION",
    "ArmPlanningError",
    "CompleteRouteSelector",
    "RouteReadinessProvider",
    "enumerate_arm_candidates",
    "load_arm_planning_profile",
    "validate_arm_planning_profile",
]
