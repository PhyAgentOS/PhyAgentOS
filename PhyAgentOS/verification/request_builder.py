"""Build a model request from Forge public contracts and immutable artifacts."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PhyAgentOS.verification.contracts import (
    EvidenceBundle,
    ForgeSessionRecord,
    VerificationEvidencePolicy,
    derive_evidence_bundle_id,
)
from PhyAgentOS.verification.outcome_projection import (
    project_terminal_outcomes,
    projection_to_dict,
)

if TYPE_CHECKING:
    from PhyAgentOS.forge.task import AgentTaskRecord


class VerificationEvidenceError(ValueError):
    pass


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant is not allowed: {value}")


@dataclass(frozen=True)
class VerificationRequest:
    content: list[dict[str, Any]]
    artifact_paths: tuple[Path, ...]
    valid_evidence_refs: frozenset[str]
    evidence: EvidenceBundle


@dataclass(frozen=True)
class _ValidatedEvidence:
    evidence: EvidenceBundle
    artifact_paths: tuple[Path, ...]
    images: tuple[tuple[str, str, bytes], ...]
    structured: dict[str, Any]
    artifact_ids: frozenset[str]


class VerificationRequestBuilder:
    def __init__(self, workspace: str | Path, *, max_image_bytes: int = 16 * 1024 * 1024):
        self.workspace = Path(workspace).expanduser().resolve()
        self.max_image_bytes = max(1, int(max_image_bytes))

    def build(
        self,
        record: ForgeSessionRecord,
        *,
        history: list[dict[str, Any]],
        lessons: str,
    ) -> VerificationRequest:
        reference = record.verification.bundle_ref
        if not reference:
            raise VerificationEvidenceError("Forge session has no Evidence Bundle")
        evidence_path, evidence = self._load_evidence(
            reference,
            expected_session_id=record.session_id,
            expected_command_id=record.command_id,
            identity_name="session",
        )
        if record.execution is None:
            raise VerificationEvidenceError("Forge session has no Execution Record")
        validated = self._validate_evidence(
            evidence_path,
            evidence,
            policy=record.request.verification.evidence_policy,
        )

        context = {
            "task_verification_contract": record.request.verification.model_dump(mode="json"),
            "execution_record": record.execution.model_dump(mode="json"),
            "evidence_bundle": validated.evidence.model_dump(mode="json"),
            "structured_evidence": validated.structured,
            "lineage_history": history,
            "lessons": lessons,
            "valid_evidence_refs": sorted(validated.artifact_ids),
        }
        return self._build_request(
            context=context,
            validated=validated,
            valid_evidence_refs=validated.artifact_ids,
        )

    def build_agent_task(
        self,
        task: AgentTaskRecord,
        *,
        events: list[dict[str, Any]],
        lessons: str,
    ) -> VerificationRequest:
        """Build one strict request for the AgentTask aggregate and its evidence."""
        reference = task.evidence_bundle_ref
        if not reference:
            raise VerificationEvidenceError("AgentTask has no Evidence Bundle")
        if not task.execution_records:
            raise VerificationEvidenceError("AgentTask has no ToolExecutionRecords")
        evidence_path, evidence = self._load_evidence(
            reference,
            expected_session_id=task.task_id,
            expected_command_id="agent_task",
            identity_name="AgentTask",
            expected_bundle_id=task.evidence_bundle_id,
        )
        validated = self._validate_evidence(
            evidence_path,
            evidence,
            policy=task.verification.evidence_policy,
        )
        execution_refs = self._validate_agent_task_lineage(task)
        overlap = validated.artifact_ids.intersection(execution_refs)
        if overlap:
            raise VerificationEvidenceError(
                "evidence references collide across execution facts and artifacts: "
                + ", ".join(sorted(overlap))
            )
        valid_refs = validated.artifact_ids | execution_refs
        records = task.execution_records
        capability_projection = project_terminal_outcomes(records)
        context = {
            "agent_task": {
                "task_id": task.task_id,
                "task_description": task.task_description,
                "status": task.status.value,
                "created_at": task.created_at.isoformat(),
                "updated_at": task.updated_at.isoformat(),
                "runtime_snapshot_ref": task.runtime_snapshot_ref,
            },
            "goal": task.verification.goal,
            "criteria": task.verification.success_criteria,
            "constraints": task.verification.constraints,
            "task_verification_contract": task.verification.model_dump(mode="json"),
            "frozen_skill_binding": (
                task.primary_skill_binding.model_dump(mode="json")
                if task.primary_skill_binding is not None
                else None
            ),
            "supporting_skill_bindings": [
                item.model_dump(mode="json") for item in task.supporting_skill_bindings
            ],
            "plan_revisions": [item.model_dump(mode="json") for item in task.revisions],
            "tool_execution_records": [item.model_dump(mode="json") for item in records],
            "gateway_terminal_results": [
                {
                    "record_id": item.record_id,
                    "tool_id": item.tool_id,
                    "semantics": item.semantics,
                    "status": item.status,
                    "invocation_id": item.invocation_id,
                    "attempt_id": item.attempt_id,
                    "response": item.response,
                    "error": item.error,
                    "evidence_refs": item.evidence_refs,
                }
                for item in records
                if item.terminal
            ],
            "capability_outcome_projections": [
                projection_to_dict(item) for item in capability_projection.projections
            ],
            "capability_outcome_projection_errors": [
                {
                    "record_id": item.record_id,
                    "code": item.code,
                    "message": item.message,
                }
                for item in capability_projection.errors
            ],
            "evidence_bundle": validated.evidence.model_dump(mode="json"),
            "structured_evidence": validated.structured,
            "evidence_errors": task.evidence_errors,
            "events": events,
            "lessons": lessons,
            "valid_evidence_refs": sorted(valid_refs),
        }
        return self._build_request(
            context=context,
            validated=validated,
            valid_evidence_refs=valid_refs,
        )

    def _load_evidence(
        self,
        reference: str,
        *,
        expected_session_id: str,
        expected_command_id: str,
        identity_name: str,
        expected_bundle_id: str | None = None,
    ) -> tuple[Path, EvidenceBundle]:
        evidence_path = self._workspace_path(reference)
        artifact_root = (self.workspace / "artifacts").resolve()
        if (
            not evidence_path.is_relative_to(artifact_root)
            or evidence_path.name != "evidence_bundle.json"
        ):
            raise VerificationEvidenceError(
                f"Evidence Bundle is not writer-owned: {reference}"
            )
        try:
            evidence = EvidenceBundle.model_validate_json(
                evidence_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise VerificationEvidenceError(f"invalid Evidence Bundle: {reference}") from exc
        if (
            evidence.session_id != expected_session_id
            or evidence.command_id != expected_command_id
        ):
            raise VerificationEvidenceError(
                f"Evidence Bundle identity does not match {identity_name}"
            )
        derived_bundle_id = derive_evidence_bundle_id(evidence)
        if evidence.bundle_id != derived_bundle_id:
            raise VerificationEvidenceError("Evidence Bundle content identity is invalid")
        if expected_bundle_id is not None and evidence.bundle_id != expected_bundle_id:
            raise VerificationEvidenceError(
                f"Evidence Bundle identity does not match {identity_name} record"
            )
        return evidence_path, evidence

    def _validate_evidence(
        self,
        evidence_path: Path,
        evidence: EvidenceBundle,
        *,
        policy: VerificationEvidencePolicy,
    ) -> _ValidatedEvidence:
        if (
            policy.minimum_association == "authoritative"
            and evidence.quality.association_quality != "authoritative"
        ):
            raise VerificationEvidenceError("evidence association is below task policy")
        if not evidence.quality.complete:
            raise VerificationEvidenceError(
                "Evidence Bundle is incomplete: "
                + ", ".join(evidence.quality.missing_requirements or ["unknown"])
            )
        self._validate_capture_window(evidence)
        self._validate_requirements(policy, evidence)

        artifact_root = (self.workspace / "artifacts").resolve()
        evidence_artifact_root = (evidence_path.parent / "evidence").resolve()
        paths: list[Path] = [evidence_path]
        images: list[tuple[str, str, bytes]] = []
        structured: dict[str, Any] = {}
        artifact_ids: set[str] = set()
        artifact_paths: set[Path] = set()
        for artifact in evidence.artifacts:
            if artifact.artifact_id in artifact_ids:
                raise VerificationEvidenceError("evidence artifact IDs must be unique")
            artifact_ids.add(artifact.artifact_id)
            if not artifact.retained:
                raise VerificationEvidenceError(
                    f"required artifact was removed by retention: {artifact.artifact_id}"
                )
            path = self._workspace_path(artifact.uri)
            if not path.is_relative_to(artifact_root) or not path.is_relative_to(
                evidence_artifact_root
            ) or path == evidence_path:
                raise VerificationEvidenceError(
                    f"evidence artifact is not writer-owned: {artifact.uri}"
                )
            if not path.is_file():
                raise VerificationEvidenceError(f"evidence artifact is missing: {artifact.uri}")
            if path in artifact_paths:
                raise VerificationEvidenceError(
                    f"evidence artifact paths must be unique: {artifact.uri}"
                )
            artifact_paths.add(path)
            data = path.read_bytes()
            if len(data) != artifact.byte_size:
                raise VerificationEvidenceError(
                    f"evidence artifact size mismatch: {artifact.artifact_id}"
                )
            if hashlib.sha256(data).hexdigest() != artifact.sha256:
                raise VerificationEvidenceError(
                    f"evidence artifact digest mismatch: {artifact.artifact_id}"
                )
            paths.append(path)
            if artifact.media_type.startswith("image/"):
                if not data or len(data) > self.max_image_bytes:
                    raise VerificationEvidenceError(
                        f"verification image exceeds size limit: {artifact.artifact_id}"
                    )
                if not self._matches_media_type(data, artifact.media_type):
                    raise VerificationEvidenceError(
                        f"verification image media type mismatch: {artifact.artifact_id}"
                    )
                images.append((artifact.artifact_id, artifact.media_type, data))
            elif artifact.media_type == "application/json":
                try:
                    structured[artifact.artifact_id] = json.loads(
                        data,
                        parse_constant=_reject_json_constant,
                    )
                except (ValueError, UnicodeDecodeError) as exc:
                    raise VerificationEvidenceError(
                        f"verification JSON is invalid: {artifact.artifact_id}"
                    ) from exc
        return _ValidatedEvidence(
            evidence=evidence,
            artifact_paths=tuple(paths),
            images=tuple(images),
            structured=structured,
            artifact_ids=frozenset(artifact_ids),
        )

    @staticmethod
    def _validate_agent_task_lineage(task: AgentTaskRecord) -> frozenset[str]:
        expected_binding_id = (
            task.primary_skill_binding.binding_id
            if task.primary_skill_binding is not None
            else None
        )
        revision_ids: set[str] = set()
        record_ids: set[str] = set()
        evidence_refs: set[str] = set()
        for revision in task.revisions:
            if revision.revision_id in revision_ids:
                raise VerificationEvidenceError("AgentTask PlanRevision IDs must be unique")
            revision_ids.add(revision.revision_id)
            if revision.skill_binding_id != expected_binding_id:
                raise VerificationEvidenceError(
                    f"PlanRevision binding does not match frozen AgentTask binding: "
                    f"{revision.revision_id}"
                )
            for record in revision.execution_records:
                if record.record_id in record_ids:
                    raise VerificationEvidenceError(
                        "AgentTask ToolExecutionRecord IDs must be unique"
                    )
                record_ids.add(record.record_id)
                if record.revision_id != revision.revision_id:
                    raise VerificationEvidenceError(
                        f"ToolExecutionRecord revision mismatch: {record.record_id}"
                    )
                if record.skill_binding_id != expected_binding_id:
                    raise VerificationEvidenceError(
                        f"ToolExecutionRecord binding mismatch: {record.record_id}"
                    )
                for reference in record.evidence_refs:
                    if not reference.strip():
                        raise VerificationEvidenceError(
                            f"ToolExecutionRecord has a blank evidence reference: "
                            f"{record.record_id}"
                        )
                    evidence_refs.add(reference)
        return frozenset(evidence_refs)

    def _build_request(
        self,
        *,
        context: dict[str, Any],
        validated: _ValidatedEvidence,
        valid_evidence_refs: frozenset[str],
    ) -> VerificationRequest:
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Determine whether every task success criterion is semantically satisfied. "
                    "Use only the supplied task contract, execution facts, and evidence to make "
                    "that decision. Lessons are advisory workflow context only; they are not "
                    "evidence and cannot establish any criterion status.\n\n"
                    + json.dumps(context, ensure_ascii=False, indent=2)
                ),
            }
        ]
        for artifact_id, media_type, data in validated.images:
            content.extend(
                [
                    {"type": "text", "text": f"EVIDENCE_ARTIFACT: {artifact_id}"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,"
                            + base64.b64encode(data).decode("ascii")
                        },
                    },
                ]
            )
        return VerificationRequest(
            content,
            validated.artifact_paths,
            valid_evidence_refs,
            validated.evidence,
        )

    @staticmethod
    def _validate_requirements(
        policy: VerificationEvidencePolicy, evidence: EvidenceBundle
    ) -> None:
        for kind in policy.required_kinds:
            for phase in ("before", "after"):
                candidates = [
                    item
                    for item in evidence.artifacts
                    if item.kind == kind and item.phase == phase
                ]
                if not candidates:
                    raise VerificationEvidenceError(
                        f"required evidence is unavailable: {phase}:{kind}"
                    )
                if "image" in kind:
                    for source in policy.required_sources:
                        if not any(item.source_id == source for item in candidates):
                            raise VerificationEvidenceError(
                                f"required evidence source is unavailable: {phase}:{kind}:{source}"
                            )

    @staticmethod
    def _validate_capture_window(evidence: EvidenceBundle) -> None:
        window = evidence.capture_window
        if (
            window.before_command_at is None
            or window.command_terminal_at is None
            or window.after_command_at is None
        ):
            raise VerificationEvidenceError("evidence capture window is incomplete")
        if not (
            window.before_command_at <= window.command_terminal_at <= window.after_command_at
        ):
            raise VerificationEvidenceError("evidence capture window ordering is invalid")

    def _workspace_path(self, relative: str) -> Path:
        path = (self.workspace / relative).resolve()
        if not path.is_relative_to(self.workspace):
            raise VerificationEvidenceError(f"artifact path escapes workspace: {relative}")
        return path

    @staticmethod
    def _matches_media_type(data: bytes, media_type: str) -> bool:
        normalized = media_type.lower().split(";", 1)[0].strip()
        if normalized in {"image/jpeg", "image/jpg"}:
            return data.startswith(b"\xff\xd8\xff")
        if normalized == "image/png":
            return data.startswith(b"\x89PNG\r\n\x1a\n")
        if normalized == "image/webp":
            return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
        return False
