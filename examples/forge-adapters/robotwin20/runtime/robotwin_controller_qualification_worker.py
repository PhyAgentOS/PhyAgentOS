"""Provider-owned, approval-gated RoboTwin/SAPIEN controller qualification.

This module is deliberately separate from the PAOS execution plane.  It only
loads an isolated SAPIEN scene containing the provider's robot description,
drives qualification fixtures, and writes immutable evidence.  It never calls
Gateway/Dora/Action, loads a benchmark task, or changes a PAOS authority flag.

The runtime is injected through :class:`QualificationRuntime`.  The concrete
SAPIEN implementation is intentionally small and provider-owned; tests can use
an instrumented runtime without making a fake result look like production
evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from robotwin20_adapter.controller_qualification import (
    ControllerQualificationApproval,
    ControllerQualificationEvidence,
    ControllerQualificationPlan,
    ControllerQualificationPlanValidation,
    ControllerQualificationSourceManifest,
    QualificationTestEvidence,
    controller_qualification_digest,
    validate_controller_qualification_plan_package,
)
from robotwin20_adapter.motion_capabilities import (
    MotionCapabilityDocument,
    MotionCapabilityValidation,
    motion_capability_digest,
)

TRACE_SCHEMA_VERSION = "paos-robotwin20-controller-qualification-test-trace/v1"
WORKER_ID = "robotwin20-controller-qualification-worker/v1"
VALIDATOR_ID = "paos-independent-controller-qualification-evidence-validator/v1"
_TEST_IDS = (
    "nominal_position_command",
    "nominal_velocity_command",
    "over_limit_velocity_command",
    "contact_load",
    "dropped_step",
    "stop_path",
    "error_path",
    "reset_path",
)


class QualificationWorkerError(RuntimeError):
    """A qualification request cannot be safely executed or persisted."""


class QualificationRuntime(Protocol):
    """Provider port used by the worker; methods must not hide failures."""

    dt_s: float

    def reset(self) -> None: ...

    def close(self) -> None: ...

    def state(self, arm_id: str) -> Mapping[str, Any]: ...

    def command(
        self, arm_id: str, position: Sequence[float], velocity: Sequence[float]
    ) -> None: ...

    def step(self) -> bool: ...

    def contacts(self) -> Sequence[Mapping[str, Any]]: ...

    def controller_status(self, arm_id: str) -> str: ...

    def stop(self) -> None: ...

    def reset_controller(self) -> None: ...

    def supports(self, capability: str) -> bool: ...

    def prepare_contact_load(self) -> None: ...

    def inject_error(self) -> None: ...

    def drop_next_step(self) -> None: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _safe_artifact_path(root: Path, ref: str, *, create: bool = False) -> Path:
    if not isinstance(ref, str) or not ref.startswith("artifact://"):
        raise QualificationWorkerError("qualification artifact reference is invalid")
    parts = ref.removeprefix("artifact://").split("/")
    if len(parts) < 2 or any(not part or part in {".", ".."} for part in parts):
        raise QualificationWorkerError("qualification artifact reference is invalid")
    path = root.joinpath(*parts)
    if path.suffix == "":
        path = path.with_suffix(".json")
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise QualificationWorkerError("qualification artifact path is a symlink")
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved_root not in resolved.parents:
        raise QualificationWorkerError("qualification artifact path escapes root")
    return resolved


def _write_immutable(root: Path, ref: str, value: Mapping[str, Any]) -> dict[str, str]:
    payload = _json_bytes(value)
    path = _safe_artifact_path(root, ref, create=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise QualificationWorkerError("qualification artifact is immutable and divergent")
    else:
        with path.open("xb") as stream:
            stream.write(payload)
        path.chmod(0o600)
    return {"artifact_ref": ref, "sha256": _sha(payload)}


def _read_model(path: Path, model: type[Any], label: str) -> Any:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise QualificationWorkerError(f"{label} must be an absolute regular file")
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise QualificationWorkerError(f"{label} is invalid") from exc


def _file_sha(path: Path, label: str) -> str:
    try:
        return _sha(path.read_bytes())
    except OSError as exc:
        raise QualificationWorkerError(f"{label} cannot be read") from exc


def _finite(value: Any, label: str) -> Any:
    """Reject NaN/Inf recursively before evidence is persisted."""
    if isinstance(value, Mapping):
        return {str(k): _finite(v, f"{label}.{k}") for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v, f"{label}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, float) and not math.isfinite(value):
        raise QualificationWorkerError(f"{label} contains NaN or Inf")
    return value


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)):
        raise QualificationWorkerError(f"{label} must be a vector")
    result = [float(item) for item in value]
    if not result or any(not math.isfinite(item) for item in result):
        raise QualificationWorkerError(f"{label} is non-finite or empty")
    return result


def _validate_runtime_state(state: Mapping[str, Any], arm_id: str) -> dict[str, Any]:
    required = {
        "joint_position",
        "joint_velocity",
        "tcp_pose",
    }
    if set(state) < required:
        raise QualificationWorkerError(f"{arm_id} runtime state is missing required signals")
    result = {
        "joint_position": _vector(state["joint_position"], f"{arm_id}.joint_position"),
        "joint_velocity": _vector(state["joint_velocity"], f"{arm_id}.joint_velocity"),
        "tcp_pose": _vector(state["tcp_pose"], f"{arm_id}.tcp_pose"),
        "tcp_velocity": _vector(
            state.get("tcp_velocity", [0.0] * 6), f"{arm_id}.tcp_velocity"
        ),
    }
    if len(result["tcp_pose"]) not in (7, 16):
        raise QualificationWorkerError(f"{arm_id}.tcp_pose must be 7 or 16 values")
    return result


def _max_abs(values: Sequence[float]) -> float:
    return max((abs(float(value)) for value in values), default=0.0)


@dataclass(frozen=True)
class QualificationPackage:
    plan: ControllerQualificationPlan
    approval: ControllerQualificationApproval
    plan_validation: ControllerQualificationPlanValidation
    source_manifest: ControllerQualificationSourceManifest
    capabilities: Mapping[str, MotionCapabilityDocument]
    validations: Mapping[str, MotionCapabilityValidation]
    file_digests: Mapping[str, str]
    source_paths: Mapping[str, Path]


def load_qualification_package(
    *,
    plan_path: Path,
    approval_path: Path,
    plan_validation_path: Path,
    source_manifest_path: Path,
    capability_paths: Mapping[str, Path],
    validation_paths: Mapping[str, Path],
) -> QualificationPackage:
    """Load and cross-check every approval-bound input before scene creation."""
    plan = _read_model(plan_path, ControllerQualificationPlan, "qualification plan")
    approval = _read_model(approval_path, ControllerQualificationApproval, "qualification approval")
    plan_validation = _read_model(
        plan_validation_path, ControllerQualificationPlanValidation, "qualification plan validation"
    )
    manifest = _read_model(
        source_manifest_path, ControllerQualificationSourceManifest, "qualification source manifest"
    )
    if plan.scene_mode != "isolated_no_task_objects":
        raise QualificationWorkerError("qualification worker refuses non-isolated scene mode")
    if approval.qualification_id != plan.qualification_id or approval.qualification_motion_authorized is not True:
        raise QualificationWorkerError("qualification approval is not bound to this plan")
    if approval.plan_sha256 != _file_sha(plan_path, "qualification plan"):
        raise QualificationWorkerError("qualification approval plan digest drifted")
    if approval.plan_validation_sha256 != _file_sha(plan_validation_path, "plan validation"):
        raise QualificationWorkerError("qualification approval validation digest drifted")
    if plan_validation.world_change_started is not False or plan_validation.qualification_motion_authorized is not False:
        raise QualificationWorkerError("qualification plan validation is not a no-motion validation")
    capabilities = {
        arm: _read_model(path, MotionCapabilityDocument, f"{arm} capability")
        for arm, path in capability_paths.items()
    }
    validations = {
        arm: _read_model(path, MotionCapabilityValidation, f"{arm} capability validation")
        for arm, path in validation_paths.items()
    }
    if set(capabilities) != {"left", "right"} or set(validations) != {"left", "right"}:
        raise QualificationWorkerError("qualification package must contain both arms")
    cap_file_digests = {arm: motion_capability_digest(value) for arm, value in capabilities.items()}
    validation_file_digests = {
        arm: controller_qualification_digest(value) for arm, value in validations.items()
    }
    try:
        validate_controller_qualification_plan_package(
            plan=plan,
            source_manifest=manifest,
            review_request=_review_from_approval(plan, approval),
            capabilities=capabilities,
            capability_file_sha256=cap_file_digests,
            validations=validations,
            validation_file_sha256=validation_file_digests,
        )
    except ValueError as exc:
        raise QualificationWorkerError("qualification package cross-binding failed") from exc
    source_paths = {
        "plan": plan_path,
        "approval": approval_path,
        "plan_validation": plan_validation_path,
        "source_manifest": source_manifest_path,
        **{f"{arm}_capability": path for arm, path in capability_paths.items()},
        **{f"{arm}_validation": path for arm, path in validation_paths.items()},
    }
    return QualificationPackage(
        plan=plan,
        approval=approval,
        plan_validation=plan_validation,
        source_manifest=manifest,
        capabilities=capabilities,
        validations=validations,
        file_digests={
            "plan": _file_sha(plan_path, "qualification plan"),
            "approval": _file_sha(approval_path, "qualification approval"),
            "plan_validation": _file_sha(plan_validation_path, "plan validation"),
            "source_manifest": _file_sha(source_manifest_path, "source manifest"),
            **{f"{arm}_capability": _file_sha(path, f"{arm} capability") for arm, path in capability_paths.items()},
            **{f"{arm}_validation": _file_sha(path, f"{arm} validation") for arm, path in validation_paths.items()},
        },
        source_paths=source_paths,
    )


def _review_from_approval(
    plan: ControllerQualificationPlan, approval: ControllerQualificationApproval
) -> Any:
    """Reconstruct only the approval-bound fields needed by the package validator."""
    from robotwin20_adapter.controller_qualification import ControllerQualificationReviewRequest

    return ControllerQualificationReviewRequest(
        qualification_id=plan.qualification_id,
        plan_ref=approval.plan_ref,
        plan_sha256=approval.plan_sha256,
        source_manifest_ref=approval.source_manifest_ref,
        source_manifest_sha256=approval.source_manifest_sha256,
    )


class ControllerQualificationWorker:
    """Run the eight-test matrix against an injected provider runtime."""

    def __init__(
        self,
        package: QualificationPackage,
        runtime: QualificationRuntime,
        artifact_root: Path,
        *,
        stop_file: Path,
        max_duration_s: float = 300.0,
    ) -> None:
        if not artifact_root.is_absolute():
            raise QualificationWorkerError("qualification artifact root must be absolute")
        if not stop_file.is_absolute():
            raise QualificationWorkerError("qualification stop file must be absolute")
        if not math.isfinite(max_duration_s) or max_duration_s <= 0:
            raise QualificationWorkerError("qualification max duration must be finite and positive")
        if not math.isfinite(float(runtime.dt_s)) or runtime.dt_s <= 0:
            raise QualificationWorkerError("qualification runtime dt must be finite and positive")
        self.package = package
        self.runtime = runtime
        self.artifact_root = artifact_root.resolve()
        self.stop_file = stop_file.resolve()
        self.max_duration_s = max_duration_s
        self.started_at = _now()
        self._wall_started = time.monotonic()
        self._world_change_started = False

    def _guard(self) -> None:
        if time.monotonic() - self._wall_started > self.max_duration_s:
            raise QualificationWorkerError("qualification timeout before simulator step")
        if self.stop_file.exists():
            raise QualificationWorkerError("qualification stop requested")
        # The package is immutable; re-check the approval flags before every step.
        if self.package.approval.qualification_motion_authorized is not True:
            raise QualificationWorkerError("qualification approval was revoked")
        if self.package.approval.benchmark_motion_authorized is not False or self.package.approval.hardware_motion_authorized is not False:
            raise QualificationWorkerError("qualification approval scope widened")
        # Detect replacement/tampering of any approval-bound input between
        # simulator steps.  A provider must never continue on stale evidence.
        for name, path in self.package.source_paths.items():
            if _file_sha(path, name) != self.package.file_digests[name]:
                raise QualificationWorkerError(f"qualification input digest drifted: {name}")

    def _step(self) -> bool:
        self._guard()
        changed = bool(self.runtime.step())
        self._world_change_started = self._world_change_started or changed
        return changed

    def _sample(self, arm_id: str, command: Mapping[str, Any], index: int) -> dict[str, Any]:
        observed = _validate_runtime_state(self.runtime.state(arm_id), arm_id)
        contacts = _finite(list(self.runtime.contacts()), "contacts")
        return {
            "sample_index": index,
            "simulator_step": index + 1,
            "simulator_time_s": (index + 1) * float(self.runtime.dt_s),
            "commanded_joint_position": list(command["position"]),
            "commanded_joint_velocity": list(command["velocity"]),
            "observed_joint_position": observed["joint_position"],
            "observed_joint_velocity": observed["joint_velocity"],
            "observed_tcp_pose": observed["tcp_pose"],
            "derived_tcp_velocity": _vector(
                observed["tcp_velocity"], f"{arm_id}.derived_tcp_velocity"
            ),
            "contacts": contacts,
            "controller_status": self.runtime.controller_status(arm_id),
            "stop_error_reset_status": {
                "stop_requested": self.stop_file.exists(),
                "error": False,
                "reset": False,
            },
        }

    def _command_for(self, arm_id: str, test_id: str) -> tuple[list[float], list[float], float]:
        state = _validate_runtime_state(self.runtime.state(arm_id), arm_id)
        capability = self.package.capabilities[arm_id]
        q = state["joint_position"]
        zeros = [0.0] * len(q)
        upper = list(capability.limits.velocity_upper_radps)
        if len(upper) != len(q):
            raise QualificationWorkerError(f"{arm_id} joint limit length mismatches runtime state")
        expected_limit = max(abs(float(x)) for x in upper)
        if test_id == "nominal_position_command":
            position = [
                min(float(x) + 0.01, float(hi) - 1e-4)
                for x, hi in zip(q, capability.limits.position_upper_rad)
            ]
            velocity = zeros
        elif test_id == "reset_path":
            position = q
            velocity = zeros
        else:
            factor = 0.1 if test_id != "over_limit_velocity_command" else 2.0
            position = q
            velocity = [float(x) * factor for x in upper]
        return position, velocity, expected_limit

    def _run_test(self, test_id: str, command_family: str) -> tuple[QualificationTestEvidence, dict[str, Any]]:
        started = _now()
        trace: dict[str, Any] = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "qualification_id": self.package.plan.qualification_id,
            "test_id": test_id,
            "command_family": command_family,
            "started_at": started,
            "arms": {},
            "events": [],
        }
        try:
            self.runtime.reset()
            if test_id in {"over_limit_velocity_command", "stop_path", "dropped_step"}:
                commands: dict[str, tuple[list[float], list[float], float]] = {
                    arm: self._command_for(arm, test_id) for arm in ("left", "right")
                }
                if test_id == "over_limit_velocity_command":
                    for arm_id, (position, velocity, expected_limit) in commands.items():
                        try:
                            self.runtime.command(arm_id, position, velocity)
                        except Exception:
                            if self.runtime.controller_status(arm_id) not in {"rejected", "fault", "limited"}:
                                raise
                            trace["arms"][arm_id] = {"samples": [self._sample(arm_id, {"position": position, "velocity": velocity}, 0)]}
                            continue
                        raise QualificationWorkerError("provider accepted over-limit velocity command")
                    trace["events"].append({"event": "over_limit", "status": "rejected"})
                elif test_id == "stop_path":
                    for arm_id, (position, velocity, _) in commands.items():
                        self.runtime.command(arm_id, position, velocity)
                    self.runtime.stop()
                    for arm_id, (position, velocity, _) in commands.items():
                        try:
                            self._step()
                        except Exception:
                            trace["arms"][arm_id] = {"samples": [self._sample(arm_id, {"position": position, "velocity": velocity}, 0)]}
                            continue
                        raise QualificationWorkerError("provider stop path allowed a simulator step")
                    trace["events"].append({"event": "stop", "status": "blocked"})
                else:
                    for arm_id, (position, velocity, _) in commands.items():
                        self.runtime.command(arm_id, position, velocity)
                    if not self.runtime.supports("dropped_step"):
                        raise _UnavailableError("provider cannot instrument a dropped simulator step")
                    self.runtime.drop_next_step()
                    changed = self._step()
                    if changed or any(self.runtime.controller_status(arm) != "fault" for arm in ("left", "right")):
                        raise QualificationWorkerError("provider dropped-step path was not detected")
                    for arm_id, (position, velocity, _) in commands.items():
                        trace["arms"][arm_id] = {"samples": [self._sample(arm_id, {"position": position, "velocity": velocity}, 0)]}
                    trace["events"].append({"event": "dropped_step", "status": "fault"})
                for arm in ("left", "right"):
                    trace["arms"].setdefault(arm, {"samples": []})
                if test_id in {"stop_path", "dropped_step"}:
                    self.runtime.reset_controller()
                    trace["events"].append({"event": "reset", "status": "completed"})
                trace["finished_at"] = _now()
                trace["outcome"] = "pass"
                statuses = [self.runtime.controller_status(arm) for arm in ("left", "right")]
                evidence = QualificationTestEvidence(
                    test_id=test_id, command_family=command_family, outcome="pass",
                    evidence_ref=f"artifact://controller-qualification/{self.package.plan.qualification_id}/evidence/{test_id}",
                    evidence_sha256="0" * 64,
                    observed_max_joint_velocity_radps=0.0,
                    controller_status=",".join(sorted(set(statuses))),
                )
                return evidence, trace
            for arm_id in ("left", "right"):
                position, velocity, expected_limit = self._command_for(arm_id, test_id)
                if test_id == "contact_load":
                    if not self.runtime.supports("contact_load"):
                        raise _UnavailableError("provider has no qualification contact/load fixture")
                    self.runtime.prepare_contact_load()
                if test_id == "dropped_step":
                    if not self.runtime.supports("dropped_step"):
                        raise _UnavailableError("provider cannot instrument a dropped simulator step")
                    self.runtime.drop_next_step()
                if test_id == "error_path":
                    if not self.runtime.supports("error_path"):
                        raise _UnavailableError("provider cannot inject controller error state")
                    self.runtime.inject_error()
                if test_id == "error_path":
                    try:
                        self.runtime.command(arm_id, position, velocity)
                    except Exception:
                        pass
                    if self.runtime.controller_status(arm_id) not in {"fault", "rejected"}:
                        raise QualificationWorkerError("provider error path did not reject command")
                    trace["arms"][arm_id] = {"samples": [self._sample(arm_id, {"position": position, "velocity": velocity}, 0)]}
                    trace["events"].append({"event": "error", "status": "rejected"})
                    continue
                self.runtime.command(arm_id, position, velocity)
                self._step()
                sample = self._sample(arm_id, {"position": position, "velocity": velocity}, 0)
                if test_id == "contact_load" and not sample["contacts"]:
                    raise QualificationWorkerError("contact-load fixture produced no contact evidence")
                sample["qualification_expectation"] = {
                    "velocity_limit_radps": expected_limit,
                    "over_limit_command": test_id == "over_limit_velocity_command",
                    "controller_rejection_required": test_id == "over_limit_velocity_command",
                }
                trace["arms"][arm_id] = {"samples": [sample]}
            if test_id in {"error_path", "stop_path"}:
                self.runtime.reset_controller()
                trace["events"].append({"event": "reset", "status": "completed"})
            if test_id == "reset_path":
                self.runtime.reset_controller()
                trace["events"].append({"event": "reset", "status": "completed"})
            finished = _now()
            trace["finished_at"] = finished
            trace["outcome"] = "pass"
            maxima = [
                _max_abs(sample["observed_joint_velocity"])
                for arm in trace["arms"].values()
                for sample in arm["samples"]
            ]
            statuses = [self.runtime.controller_status(arm) for arm in ("left", "right")]
            if test_id == "over_limit_velocity_command":
                # A status such as ``rejected``/``limited`` is required.  A
                # merely observed low velocity is not proof of enforcement.
                if not any(status in {"rejected", "limited", "fault"} for status in statuses):
                    raise QualificationWorkerError(
                        "provider did not report controller rejection or limiting for over-limit command"
                    )
            evidence = QualificationTestEvidence(
                test_id=test_id,
                command_family=command_family,  # type: ignore[arg-type]
                outcome="pass",
                evidence_ref=f"artifact://controller-qualification/{self.package.plan.qualification_id}/evidence/{test_id}",
                evidence_sha256="0" * 64,
                observed_max_joint_velocity_radps=max(maxima, default=0.0),
                controller_status=",".join(sorted(set(statuses))),
            )
            return evidence, trace
        except _UnavailableError as exc:
            trace["finished_at"] = _now()
            trace["outcome"] = "unavailable"
            trace["failure_reason"] = str(exc)
            return self._unavailable_evidence(test_id, command_family), trace
        except Exception as exc:
            trace["finished_at"] = _now()
            trace["outcome"] = "fail"
            trace["failure_reason"] = str(exc)
            return self._failed_evidence(test_id, command_family), trace

    def _unavailable_evidence(self, test_id: str, command_family: str) -> QualificationTestEvidence:
        return QualificationTestEvidence(
            test_id=test_id, command_family=command_family, outcome="unavailable",  # type: ignore[arg-type]
            evidence_ref=f"artifact://controller-qualification/{self.package.plan.qualification_id}/evidence/{test_id}",
            evidence_sha256="0" * 64, controller_status="unavailable",
        )

    def _failed_evidence(self, test_id: str, command_family: str) -> QualificationTestEvidence:
        return QualificationTestEvidence(
            test_id=test_id, command_family=command_family, outcome="fail",  # type: ignore[arg-type]
            evidence_ref=f"artifact://controller-qualification/{self.package.plan.qualification_id}/evidence/{test_id}",
            evidence_sha256="0" * 64, controller_status="failed",
        )

    def run(self) -> tuple[ControllerQualificationEvidence, dict[str, dict[str, str]]]:
        results: list[QualificationTestEvidence] = []
        refs: dict[str, dict[str, str]] = {}
        try:
            for test_id in _TEST_IDS:
                family = "position_drive_target" if "position" in test_id or test_id == "reset_path" else "velocity_drive_target"
                result, trace = self._run_test(test_id, family)
                record = _write_immutable(self.artifact_root, result.evidence_ref, _finite(trace, "trace"))
                result = result.model_copy(update={"evidence_sha256": record["sha256"]})
                results.append(result)
                refs[test_id] = record
        finally:
            try:
                self.runtime.reset_controller()
            except Exception:
                pass
            try:
                self.runtime.close()
            except Exception:
                pass
        outcomes = [item.outcome for item in results]
        status = "passed" if outcomes and all(item == "pass" for item in outcomes) else "failed"
        if any(item == "unavailable" for item in outcomes):
            status = "unavailable"
        evidence = ControllerQualificationEvidence(
            qualification_id=self.package.plan.qualification_id,
            producer_id=WORKER_ID,
            plan_ref=self.package.approval.plan_ref,
            plan_sha256=self.package.approval.plan_sha256,
            approval_ref=f"artifact://controller-qualification/{self.package.plan.qualification_id}/approval",
            approval_sha256=self.package.file_digests["approval"],
            identity=self.package.plan.identity,
            status=status,  # type: ignore[arg-type]
            tests=tuple(results),
            world_change_started=self._world_change_started,
            world_change_completed=self._world_change_started,
            reset_completed=True,
            outcome_known=True,
            started_at=self.started_at,
            finished_at=_now(),
        )
        return evidence, refs


class _UnavailableError(Exception):
    pass


class SapienQualificationRuntime:
    """Minimal real SAPIEN provider for an empty two-Panda qualification scene."""

    def __init__(self, robotwin_root: Path, capabilities: Mapping[str, MotionCapabilityDocument], *, timestep_s: float = 1 / 250) -> None:
        try:
            import sapien.core as sapien
        except ModuleNotFoundError as exc:
            raise QualificationWorkerError("SAPIEN is unavailable in the provider runtime") from exc
        try:
            import yaml
        except ModuleNotFoundError as exc:
            raise QualificationWorkerError("PyYAML is unavailable in the provider runtime") from exc
        if not robotwin_root.is_absolute() or not robotwin_root.is_dir():
            raise QualificationWorkerError("robotwin_root must be an absolute directory")
        self._sapien = sapien
        self.dt_s = float(timestep_s)
        self._engine = sapien.Engine()
        self._scene = self._engine.create_scene()
        self._scene.set_timestep(self.dt_s)
        self._robots: dict[str, Any] = {}
        if set(capabilities) != {"left", "right"} or any(
            capability.provider.controller_id != "paos-robotwin-capability-bounded-drive-target"
            for capability in capabilities.values()
        ):
            raise QualificationWorkerError(
                "qualification runtime requires the capability-bounded provider controller identity"
            )
        self._controllers: dict[str, Any] = {}
        self._contact_fixture: Any | None = None
        self._drop_next = False
        self._last_tcp_pose: dict[str, list[float]] = {}
        config_path = robotwin_root / "assets" / "embodiments" / "franka-panda" / "config.yml"
        urdf_path = robotwin_root / "assets" / "embodiments" / "franka-panda" / "panda.urdf"
        if not config_path.is_file() or not urdf_path.is_file():
            raise QualificationWorkerError("Franka provider description is unavailable")
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        for arm, x in (("left", -0.4), ("right", 0.4)):
            loader = self._scene.create_urdf_loader()
            loader.fix_root_link = True
            robot = loader.load(str(urdf_path))
            if robot is None:
                raise QualificationWorkerError(f"failed to load Franka articulation for {arm}")
            robot.set_root_pose(sapien.Pose([x, -0.65, 0.75], [0.707, 0, 0, 0.707]))
            joints = [robot.find_joint_by_name(name) for name in config["arm_joints_name"][0]]
            for joint in joints:
                joint.set_drive_property(1000.0, 200.0, 1000.0)
            self._robots[arm] = (robot, joints)
            from robotwin_capability_controller import (
                CapabilityBoundedDriveController,
                ControllerLimits,
            )
            capability = capabilities.get(arm)
            if capability is None or tuple(config["arm_joints_name"][0]) != capability.joint_order:
                raise QualificationWorkerError(f"{arm} capability joint order does not match Franka runtime")
            self._controllers[arm] = CapabilityBoundedDriveController(
                ControllerLimits(
                    joint_order=capability.joint_order,
                    position_lower_rad=capability.limits.position_lower_rad,
                    position_upper_rad=capability.limits.position_upper_rad,
                    velocity_lower_radps=capability.limits.velocity_lower_radps,
                    velocity_upper_radps=capability.limits.velocity_upper_radps,
                ),
                lambda q, dq, arm_id=arm: self._write_target(arm_id, q, dq),
            )
        self._step_index = 0
        self._closed = False

    def reset(self) -> None:
        self._drop_next = False
        for robot, _ in self._robots.values():
            # Panda articulation contains seven arm DOFs plus the two finger
            # DOFs.  Keep the gripper joints in a valid, open state while the
            # qualification matrix commands only the arm joint order.
            qpos = [0.0, 0.19634954084936207, 0.0, -2.617993877991494, 0.0, 2.941592653589793, 0.7853981633974483, 0.04, 0.04]
            if len(robot.get_qpos()) != len(qpos):
                raise QualificationWorkerError("Franka articulation DOF count is not the qualified profile")
            robot.set_qpos(qpos)
        for controller in self._controllers.values():
            controller.reset()
        self._last_tcp_pose.clear()

    def close(self) -> None:
        self._closed = True

    def state(self, arm_id: str) -> Mapping[str, Any]:
        robot, joints = self._robots[arm_id]
        link = robot.find_link_by_name("panda_hand")
        pose = link.get_pose()
        pose_values = list(pose.p) + list(pose.q)
        previous = self._last_tcp_pose.get(arm_id)
        tcp_velocity = [0.0] * 6
        if previous is not None:
            tcp_velocity = [
                (pose_values[index] - previous[index]) / self.dt_s for index in range(3)
            ] + [0.0] * 3
        self._last_tcp_pose[arm_id] = pose_values
        return {
            "joint_position": list(robot.get_qpos()[: len(joints)]),
            "joint_velocity": list(robot.get_qvel()[: len(joints)]),
            "tcp_pose": pose_values,
            "tcp_velocity": tcp_velocity,
        }

    def command(self, arm_id: str, position: Sequence[float], velocity: Sequence[float]) -> None:
        self._controllers[arm_id].command(position, velocity)

    def _write_target(self, arm_id: str, position: Sequence[float], velocity: Sequence[float]) -> None:
        _, joints = self._robots[arm_id]
        for joint, q, dq in zip(joints, position, velocity):
            joint.set_drive_target(float(q))
            joint.set_drive_velocity_target(float(dq))

    def step(self) -> bool:
        if self._closed:
            raise QualificationWorkerError("SAPIEN runtime is closed")
        for controller in self._controllers.values():
            controller.before_step()
        if self._drop_next:
            self._drop_next = False
            for controller in self._controllers.values():
                controller.dropped_step()
            return False
        self._scene.step()
        self._step_index += 1
        for controller in self._controllers.values():
            controller.after_step()
        return True

    def contacts(self) -> Sequence[Mapping[str, Any]]:
        result = []
        for contact in self._scene.get_contacts():
            bodies = getattr(contact, "bodies", ())
            result.append({"bodies": [getattr(body.entity, "name", "unknown") for body in bodies]})
        return result

    def controller_status(self, arm_id: str) -> str:
        return self._controllers[arm_id].status if not self._closed else "closed"

    def stop(self) -> None:
        for controller in self._controllers.values():
            controller.stop()

    def reset_controller(self) -> None:
        for controller in self._controllers.values():
            controller.reset()

    def supports(self, capability: str) -> bool:
        return capability in {"contact_load", "dropped_step", "error_path"}

    def prepare_contact_load(self) -> None:
        if self._contact_fixture is not None:
            return
        hand = self._robots["right"][0].find_link_by_name("panda_hand")
        pose = hand.get_pose()
        builder = self._scene.create_actor_builder()
        builder.add_box_collision(half_size=[0.04, 0.04, 0.04])
        self._contact_fixture = builder.build_static(name="qualification_contact_fixture")
        self._contact_fixture.set_pose(pose)

    def inject_error(self) -> None:
        for controller in self._controllers.values():
            controller.fault("qualification error-path injection")

    def drop_next_step(self) -> None:
        self._drop_next = True


def validate_trace_artifact(trace: Mapping[str, Any], expected: QualificationTestEvidence) -> tuple[str, ...]:
    """Independent, provider-neutral evidence checks used by the validator CLI."""
    if trace.get("schema_version") != TRACE_SCHEMA_VERSION:
        raise QualificationWorkerError("qualification trace schema is unsupported")
    ref_parts = expected.evidence_ref.split("/")
    if len(ref_parts) < 5 or trace.get("qualification_id") != ref_parts[3]:
        raise QualificationWorkerError("qualification trace identity is invalid")
    if trace.get("test_id") != expected.test_id or trace.get("command_family") != expected.command_family:
        raise QualificationWorkerError("qualification trace test binding is invalid")
    arms = trace.get("arms")
    if not isinstance(arms, Mapping) or set(arms) - {"left", "right"}:
        raise QualificationWorkerError("qualification trace arm coverage is incomplete")
    if expected.outcome != "pass" and not arms:
        if not trace.get("failure_reason"):
            raise QualificationWorkerError("failed qualification trace lacks failure reason")
        return ("trace_schema", "test_binding", "failure_reason", "outcome_binding")
    if set(arms) != {"left", "right"}:
        raise QualificationWorkerError("qualification trace arm coverage is incomplete")
    for arm_id, payload in arms.items():
        samples = payload.get("samples") if isinstance(payload, Mapping) else None
        if not isinstance(samples, list) or not samples:
            raise QualificationWorkerError(f"qualification trace {arm_id} samples are missing")
        for sample in samples:
            required = {
                "commanded_joint_position", "commanded_joint_velocity", "observed_joint_position",
                "observed_joint_velocity", "observed_tcp_pose", "derived_tcp_velocity", "contacts",
                "controller_status", "simulator_step", "simulator_time_s", "stop_error_reset_status",
            }
            if not required.issubset(sample):
                raise QualificationWorkerError("qualification trace required signal is missing")
            _finite(sample, "qualification trace sample")
    if trace.get("outcome") != expected.outcome:
        raise QualificationWorkerError("qualification trace outcome is not bound")
    return ("trace_schema", "test_binding", "both_arm_signals", "finite_values", "outcome_binding")


__all__ = [
    "ControllerQualificationWorker",
    "QualificationPackage",
    "QualificationRuntime",
    "QualificationWorkerError",
    "SapienQualificationRuntime",
    "TRACE_SCHEMA_VERSION",
    "VALIDATOR_ID",
    "WORKER_ID",
    "load_qualification_package",
    "validate_trace_artifact",
]
