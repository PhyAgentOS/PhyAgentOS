"""Persist Forge observations as validated public evidence artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from PhyAgentOS.forge.observation import (
    CapturedImage,
    CapturedState,
    ObservationSnapshot,
)
from PhyAgentOS.utils.atomic_file import atomic_write_bytes, atomic_write_text
from PhyAgentOS.verification.contracts import (
    EvidenceArtifact,
    EvidenceBundle,
    EvidenceCaptureWindow,
    EvidenceQuality,
    ExecutionRecord,
    derive_evidence_bundle_id,
    evidence_bundle_semantic_payload,
)


class _SnapshotManifestEntry(BaseModel):
    """Digest-bound writer-owned artifact entry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["rgb_image", "robot_state"]
    source_id: str = Field(min_length=1)
    sequence: int | None = Field(default=None, ge=0)
    captured_at: float | None = Field(default=None, allow_inf_nan=False)
    received_at: datetime
    media_type: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)

    @field_validator("received_at")
    @classmethod
    def require_received_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("snapshot entry received_at must include a timezone")
        return value

    @field_validator("uri")
    @classmethod
    def require_relative_uri(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("snapshot entry uri must be workspace-relative")
        return normalized

    @model_validator(mode="after")
    def validate_kind_contract(self) -> "_SnapshotManifestEntry":
        if self.kind == "rgb_image":
            if self.sequence is None:
                raise ValueError("rgb_image snapshot entry requires sequence")
            if self.media_type.lower() not in {
                "image/jpeg",
                "image/jpg",
                "image/png",
                "image/webp",
            }:
                raise ValueError("rgb_image snapshot entry has unsupported media_type")
        elif (
            self.source_id != "ws/state"
            or self.sequence is not None
            or self.captured_at is not None
            or self.media_type != "application/json"
        ):
            raise ValueError("robot_state snapshot entry has invalid identity fields")
        return self


class _SnapshotManifest(BaseModel):
    """Strict v2 snapshot manifest; v1 manifests fail closed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["forge_observation_snapshot_v2"]
    phase: Literal["before", "after"]
    captured_at: datetime
    # Empty snapshots are valid capture records when the collector timed out;
    # Evidence Bundle quality, not manifest parsing, records missing requirements.
    entries: tuple[_SnapshotManifestEntry, ...]

    @field_validator("captured_at")
    @classmethod
    def require_capture_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("snapshot captured_at must include a timezone")
        return value


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant is not allowed: {value}")


class ForgeEvidenceWriter:
    def __init__(
        self,
        workspace: str | Path,
        session_id: str,
        command_id: str,
        *,
        artifact_namespace: str = "forge",
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        if (
            not isinstance(session_id, str)
            or not session_id.strip()
            or session_id.strip() in {".", ".."}
            or "/" in session_id
            or "\\" in session_id
        ):
            raise ValueError("evidence session_id must be non-empty and path-safe")
        if not isinstance(command_id, str) or not command_id.strip():
            raise ValueError("evidence command_id must be non-empty")
        self.session_id = session_id
        self.command_id = command_id
        namespace = Path(artifact_namespace)
        if (
            not artifact_namespace.strip()
            or namespace == Path(".")
            or namespace.is_absolute()
            or ".." in namespace.parts
        ):
            raise ValueError("artifact namespace must be a safe relative path")
        self.artifact_namespace = namespace.as_posix()
        self.artifact_dir = self.workspace / "artifacts" / namespace / session_id
        if not self.artifact_dir.resolve().is_relative_to(self.workspace):
            raise ValueError("Forge artifact directory escapes workspace")
        self.evidence_dir = self.artifact_dir / "evidence"

    def write_snapshot(self, phase: str, snapshot: ObservationSnapshot) -> str:
        if phase not in {"before", "after"}:
            raise ValueError(f"unsupported evidence phase: {phase}")
        snapshot_path = self.artifact_dir / f"{phase}_snapshot.json"
        if snapshot_path.exists():
            existing = self.load_snapshot(str(snapshot_path.relative_to(self.workspace)))
            if existing != snapshot:
                raise ValueError(
                    f"immutable {phase} evidence snapshot already exists with different content"
                )
            return str(snapshot_path.relative_to(self.workspace))
        planned_images: list[tuple[str, CapturedImage, Path]] = []
        planned_paths: set[Path] = set()
        for source, image in snapshot.images.items():
            if image.source_id != source:
                raise ValueError(
                    f"snapshot image source mismatch: key={source!r}, image={image.source_id!r}"
                )
            path = self._evidence_path(
                self._image_filename(phase, source, image.sequence, image.media_type)
            )
            self._register_planned_path(path, planned_paths)
            planned_images.append((source, image, path))

        state_path: Path | None = None
        if snapshot.state is not None:
            state_path = self._evidence_path(f"{phase}_robot_state.json")
            self._register_planned_path(state_path, planned_paths)

        entries: list[dict] = []
        planned_artifacts: list[tuple[Path, bytes]] = []
        for source, image, path in planned_images:
            planned_artifacts.append((path, image.data))
            entries.append(
                {
                    "kind": "rgb_image",
                    "source_id": source,
                    "sequence": image.sequence,
                    "captured_at": image.captured_at,
                    "received_at": image.received_at.isoformat(),
                    "media_type": image.media_type,
                    "uri": str(path.relative_to(self.workspace)),
                    "sha256": hashlib.sha256(image.data).hexdigest(),
                    "byte_size": len(image.data),
                }
            )
        if snapshot.state is not None and state_path is not None:
            state_data = json.dumps(
                snapshot.state.payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            planned_artifacts.append((state_path, state_data))
            entries.append(
                {
                    "kind": "robot_state",
                    "source_id": "ws/state",
                    "sequence": None,
                    "captured_at": None,
                    "received_at": snapshot.state.received_at.isoformat(),
                    "media_type": "application/json",
                    "uri": str(state_path.relative_to(self.workspace)),
                    "sha256": hashlib.sha256(state_data).hexdigest(),
                    "byte_size": len(state_data),
                }
            )
        manifest = _SnapshotManifest.model_validate(
            {
                "version": "forge_observation_snapshot_v2",
                "phase": phase,
                "captured_at": snapshot.captured_at.isoformat(),
                "entries": entries,
            }
        )
        for artifact_path, data in planned_artifacts:
            self._check_immutable_bytes(artifact_path, data)
        for artifact_path, data in planned_artifacts:
            self._write_immutable_bytes(artifact_path, data)
        path = self.artifact_dir / f"{phase}_snapshot.json"
        atomic_write_text(
            path,
            json.dumps(
                manifest.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        return str(path.relative_to(self.workspace))

    def snapshot_projection_identity(self, reference: str) -> tuple[str, str]:
        """Return the phase and opaque URI for one writer-owned snapshot."""

        _, manifest = self._read_manifest(reference)
        self._materialize_snapshot(manifest)
        digest = _canonical_digest(manifest.model_dump(mode="json"))
        return (
            manifest.phase,
            f"evidence://{self.artifact_namespace}/{self.session_id}/"
            f"{manifest.phase}_snapshot/{digest}",
        )

    def snapshot_projection_ref(self, reference: str) -> str:
        """Return the stable opaque evidence URI for a writer-owned snapshot."""

        return self.snapshot_projection_identity(reference)[1]

    def load_snapshot(self, reference: str) -> ObservationSnapshot:
        snapshot, _, _ = self._load_snapshot(reference)
        return snapshot

    def _load_snapshot(
        self, reference: str, *, expected_phase: str | None = None
    ) -> tuple[ObservationSnapshot, dict[str, Path], Path | None]:
        _, manifest = self._read_manifest(reference, expected_phase=expected_phase)
        return self._materialize_snapshot(manifest)

    def _read_manifest(
        self,
        reference: str,
        *,
        expected_phase: str | None = None,
    ) -> tuple[Path, _SnapshotManifest]:
        path = self._workspace_path(reference)
        expected_names = {"before_snapshot.json": "before", "after_snapshot.json": "after"}
        path_phase = expected_names.get(path.name)
        expected_path = (self.artifact_dir / path.name).resolve()
        if path_phase is None or path != expected_path:
            raise ValueError("snapshot reference is not a writer-owned before/after snapshot")
        try:
            manifest = _SnapshotManifest.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise ValueError("evidence snapshot manifest is invalid") from exc
        if manifest.phase != path_phase:
            raise ValueError("evidence snapshot manifest phase does not match its path")
        if expected_phase is not None and manifest.phase != expected_phase:
            raise ValueError(
                f"evidence snapshot phase mismatch: expected {expected_phase}, "
                f"got {manifest.phase}"
            )
        return path, manifest

    def _materialize_snapshot(
        self, manifest: _SnapshotManifest
    ) -> tuple[ObservationSnapshot, dict[str, Path], Path | None]:
        images: dict[str, CapturedImage] = {}
        image_paths: dict[str, Path] = {}
        state: CapturedState | None = None
        state_path: Path | None = None
        evidence_root = self.evidence_dir.resolve()
        for entry in manifest.entries:
            artifact_path = self._workspace_path(entry.uri)
            if not artifact_path.is_relative_to(evidence_root):
                raise ValueError("snapshot artifact is not writer-owned")
            data = artifact_path.read_bytes()
            if len(data) != entry.byte_size:
                raise ValueError(f"snapshot artifact size mismatch: {entry.uri}")
            if hashlib.sha256(data).hexdigest() != entry.sha256:
                raise ValueError(f"snapshot artifact digest mismatch: {entry.uri}")
            if entry.kind == "rgb_image":
                if entry.source_id in images:
                    raise ValueError(
                        f"duplicate snapshot image source: {entry.source_id}"
                    )
                assert entry.sequence is not None
                image = CapturedImage(
                    source_id=entry.source_id,
                    sequence=entry.sequence,
                    captured_at=entry.captured_at,
                    received_at=entry.received_at,
                    media_type=entry.media_type,
                    data=data,
                )
                images[image.source_id] = image
                image_paths[image.source_id] = artifact_path
            elif entry.kind == "robot_state":
                if state is not None:
                    raise ValueError("snapshot contains multiple robot_state entries")
                payload = json.loads(data, parse_constant=_reject_json_constant)
                if not isinstance(payload, dict):
                    raise ValueError("snapshot robot_state payload must be an object")
                state = CapturedState(entry.received_at, payload)
                state_path = artifact_path
        return (
            ObservationSnapshot(
                captured_at=manifest.captured_at,
                images=images,
                state=state,
            ),
            image_paths,
            state_path,
        )

    def write_bundle(
        self,
        *,
        before_ref: str | None,
        after_ref: str | None,
        terminal_observed_at: datetime | None,
        required_sources: list[str],
        required_kinds: list[str],
        errors: list[str],
    ) -> tuple[EvidenceBundle, str]:
        artifacts: list[EvidenceArtifact] = []
        missing: list[str] = []
        bundle_errors = list(errors)
        snapshots: dict[str, ObservationSnapshot | None] = {}
        for phase, reference in (("before", before_ref), ("after", after_ref)):
            if reference is None:
                snapshots[phase] = None
                missing.append(f"{phase}:snapshot")
                continue
            try:
                snapshot, image_paths, state_path = self._load_snapshot(
                    reference,
                    expected_phase=phase,
                )
                snapshots[phase] = snapshot
            except Exception as exc:
                snapshots[phase] = None
                missing.append(f"{phase}:snapshot")
                bundle_errors.append(f"{phase} snapshot invalid: {exc}")
                continue
            snapshot = snapshots[phase]
            assert snapshot is not None
            for source in required_sources:
                if source not in snapshot.images:
                    missing.append(f"{phase}:rgb_image:{source}")
            for image in snapshot.images.values():
                artifacts.append(
                    self._image_artifact(phase, image, image_paths[image.source_id])
                )
            if snapshot.state is not None:
                if state_path is None:
                    raise ValueError(f"{phase} snapshot state has no artifact path")
                artifacts.append(self._state_artifact(phase, snapshot.state, state_path))
            elif "robot_state" in required_kinds:
                missing.append(f"{phase}:robot_state:ws/state")
        for phase in ("before", "after"):
            for kind in required_kinds:
                if not any(item.phase == phase and item.kind == kind for item in artifacts):
                    value = f"{phase}:{kind}"
                    if value not in missing:
                        missing.append(value)
        before = snapshots.get("before")
        after = snapshots.get("after")
        if terminal_observed_at is None:
            missing.append("capture_window:terminal")
        artifacts.sort(
            key=lambda item: (
                item.phase,
                item.kind,
                item.source_id,
                -1 if item.sequence is None else item.sequence,
                item.artifact_id,
            )
        )
        quality = EvidenceQuality(
            complete=not missing,
            association_quality="best_effort",
            missing_requirements=list(dict.fromkeys(missing)),
            errors=list(dict.fromkeys(bundle_errors)),
        )
        bundle = EvidenceBundle(
            bundle_id="pending",
            session_id=self.session_id,
            command_id=self.command_id,
            capture_window=EvidenceCaptureWindow(
                before_command_at=before.captured_at if before else None,
                command_terminal_at=terminal_observed_at,
                after_command_at=after.captured_at if after else None,
            ),
            artifacts=artifacts,
            quality=quality,
        )
        bundle = bundle.model_copy(update={"bundle_id": derive_evidence_bundle_id(bundle)})
        semantic_payload = evidence_bundle_semantic_payload(bundle)
        path = self.artifact_dir / "evidence_bundle.json"
        if path.exists():
            try:
                existing = EvidenceBundle.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except Exception as exc:
                raise ValueError("persisted Evidence Bundle is invalid") from exc
            existing_payload = evidence_bundle_semantic_payload(existing)
            expected_id = derive_evidence_bundle_id(existing)
            if existing.bundle_id != expected_id:
                raise ValueError("persisted Evidence Bundle identity is invalid")
            if existing_payload != semantic_payload:
                raise ValueError(
                    "immutable Evidence Bundle already exists with different content"
                )
            return existing, str(path.relative_to(self.workspace))
        atomic_write_text(
            path,
            json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
        )
        return bundle, str(path.relative_to(self.workspace))

    def write_execution(self, execution) -> str:
        path = self.artifact_dir / "execution_record.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != execution.model_dump(mode="json"):
                raise ValueError("immutable execution record already exists with different content")
        else:
            atomic_write_text(
                path,
                json.dumps(
                    execution.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
        return str(path.relative_to(self.workspace))

    def load_execution(self) -> ExecutionRecord | None:
        path = self.artifact_dir / "execution_record.json"
        if not path.exists():
            return None
        try:
            return ExecutionRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError("persisted Execution Record is invalid") from exc

    def _image_artifact(
        self, phase: str, image: CapturedImage, path: Path
    ) -> EvidenceArtifact:
        return self._artifact(
            path,
            phase=phase,
            kind="rgb_image",
            source_id=image.source_id,
            captured_at=image.captured_at,
            received_at=image.received_at,
            sequence=image.sequence,
            media_type=image.media_type,
        )

    def _state_artifact(
        self, phase: str, state: CapturedState, path: Path
    ) -> EvidenceArtifact:
        return self._artifact(
            path,
            phase=phase,
            kind="robot_state",
            source_id="ws/state",
            captured_at=None,
            received_at=state.received_at,
            sequence=None,
            media_type="application/json",
        )

    def _artifact(
        self,
        path: Path,
        *,
        phase: str,
        kind: str,
        source_id: str,
        captured_at,
        received_at,
        sequence,
        media_type: str,
    ) -> EvidenceArtifact:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        identity = hashlib.sha256(
            f"{phase}:{kind}:{source_id}:{sequence}:{digest}".encode()
        ).hexdigest()
        return EvidenceArtifact(
            artifact_id=f"artifact_{identity[:20]}",
            phase=phase,
            kind=kind,
            source_id=source_id,
            captured_at=captured_at,
            received_at=received_at,
            sequence=sequence,
            media_type=media_type,
            sha256=digest,
            byte_size=len(data),
            uri=str(path.relative_to(self.workspace)),
        )

    def _workspace_path(self, relative: str) -> Path:
        path = (self.workspace / relative).resolve()
        if not path.is_relative_to(self.workspace):
            raise ValueError(f"artifact path escapes workspace: {relative}")
        return path

    def _image_filename(
        self, phase: str, source_id: str, sequence: int, media_type: str
    ) -> str:
        suffix = self._suffix_for(media_type)
        if re.fullmatch(r"[a-z0-9]+", suffix) is None:
            raise ValueError(f"invalid evidence file extension: {suffix!r}")
        safe_label = self._safe_name(source_id)[:40]
        source_digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()
        return f"{phase}_{safe_label}_{source_digest}_{sequence}.{suffix}"

    def _evidence_path(self, filename: str) -> Path:
        path = (self.evidence_dir / filename).resolve()
        if not path.is_relative_to(self.evidence_dir.resolve()):
            raise ValueError(f"evidence path escapes evidence directory: {filename}")
        return path

    @staticmethod
    def _check_immutable_bytes(path: Path, data: bytes) -> None:
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError(
                    f"immutable evidence artifact already exists with different content: "
                    f"{path.name}"
                )

    @staticmethod
    def _write_immutable_bytes(path: Path, data: bytes) -> None:
        ForgeEvidenceWriter._check_immutable_bytes(path, data)
        if path.exists():
            return
        atomic_write_bytes(path, data)

    @staticmethod
    def _register_planned_path(path: Path, planned_paths: set[Path]) -> None:
        if path in planned_paths:
            raise ValueError(f"duplicate evidence target path: {path.name}")
        planned_paths.add(path)

    @staticmethod
    def _safe_name(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("._")[:80] or "source"

    @staticmethod
    def _suffix_for(media_type: str) -> str:
        return {
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
        }.get(media_type.lower(), "img")
