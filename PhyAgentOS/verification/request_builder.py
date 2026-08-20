"""Build a model request from Forge public contracts and immutable artifacts."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PhyAgentOS.verification.contracts import EvidenceBundle, ForgeSessionRecord


class VerificationEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class VerificationRequest:
    content: list[dict[str, Any]]
    artifact_paths: tuple[Path, ...]
    valid_evidence_refs: frozenset[str]
    evidence: EvidenceBundle


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
        evidence_path = self._workspace_path(reference)
        try:
            evidence = EvidenceBundle.model_validate_json(
                evidence_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise VerificationEvidenceError(f"invalid Evidence Bundle: {reference}") from exc
        if evidence.session_id != record.session_id or evidence.command_id != record.command_id:
            raise VerificationEvidenceError("Evidence Bundle identity does not match session")
        if record.execution is None:
            raise VerificationEvidenceError("Forge session has no Execution Record")
        minimum = record.request.verification.evidence_policy.minimum_association
        if minimum == "authoritative" and evidence.quality.association_quality != "authoritative":
            raise VerificationEvidenceError("evidence association is below task policy")
        if not evidence.quality.complete:
            raise VerificationEvidenceError(
                "Evidence Bundle is incomplete: "
                + ", ".join(evidence.quality.missing_requirements or ["unknown"])
            )
        self._validate_capture_window(evidence)
        self._validate_requirements(record, evidence)

        paths: list[Path] = [evidence_path]
        images: list[tuple[str, str, bytes]] = []
        structured: dict[str, Any] = {}
        artifact_ids: set[str] = set()
        for artifact in evidence.artifacts:
            if artifact.artifact_id in artifact_ids:
                raise VerificationEvidenceError("evidence artifact IDs must be unique")
            artifact_ids.add(artifact.artifact_id)
            if not artifact.retained:
                raise VerificationEvidenceError(
                    f"required artifact was removed by retention: {artifact.artifact_id}"
                )
            path = self._workspace_path(artifact.uri)
            if not path.is_file():
                raise VerificationEvidenceError(f"evidence artifact is missing: {artifact.uri}")
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
                    structured[artifact.artifact_id] = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise VerificationEvidenceError(
                        f"verification JSON is invalid: {artifact.artifact_id}"
                    ) from exc

        context = {
            "task_verification_contract": record.request.verification.model_dump(mode="json"),
            "execution_record": record.execution.model_dump(mode="json"),
            "evidence_bundle": evidence.model_dump(mode="json"),
            "structured_evidence": structured,
            "lineage_history": history,
            "lessons": lessons,
            "valid_evidence_refs": sorted(artifact_ids),
        }
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Determine whether every task success criterion is semantically satisfied. "
                    "Use only the supplied execution facts and evidence.\n\n"
                    + json.dumps(context, ensure_ascii=False, indent=2)
                ),
            }
        ]
        for artifact_id, media_type, data in images:
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
        return VerificationRequest(content, tuple(paths), frozenset(artifact_ids), evidence)

    @staticmethod
    def _validate_requirements(
        record: ForgeSessionRecord, evidence: EvidenceBundle
    ) -> None:
        policy = record.request.verification.evidence_policy
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
