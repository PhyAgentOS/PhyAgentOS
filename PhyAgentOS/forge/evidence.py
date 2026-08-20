"""Persist Forge observations as validated public evidence artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

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
)


class ForgeEvidenceWriter:
    def __init__(self, workspace: str | Path, session_id: str, command_id: str) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.session_id = session_id
        self.command_id = command_id
        self.artifact_dir = self.workspace / "artifacts" / "forge" / session_id
        if not self.artifact_dir.resolve().is_relative_to(self.workspace):
            raise ValueError("Forge artifact directory escapes workspace")
        self.evidence_dir = self.artifact_dir / "evidence"

    def write_snapshot(self, phase: str, snapshot: ObservationSnapshot) -> str:
        if phase not in {"before", "after"}:
            raise ValueError(f"unsupported evidence phase: {phase}")
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
        for source, image, path in planned_images:
            atomic_write_bytes(path, image.data)
            entries.append(
                {
                    "kind": "rgb_image",
                    "source_id": source,
                    "sequence": image.sequence,
                    "captured_at": image.captured_at,
                    "received_at": image.received_at.isoformat(),
                    "media_type": image.media_type,
                    "uri": str(path.relative_to(self.workspace)),
                }
            )
        if snapshot.state is not None and state_path is not None:
            state_data = json.dumps(
                snapshot.state.payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            atomic_write_bytes(state_path, state_data)
            entries.append(
                {
                    "kind": "robot_state",
                    "source_id": "ws/state",
                    "sequence": None,
                    "captured_at": None,
                    "received_at": snapshot.state.received_at.isoformat(),
                    "media_type": "application/json",
                    "uri": str(state_path.relative_to(self.workspace)),
                }
            )
        manifest = {
            "version": "forge_observation_snapshot_v1",
            "phase": phase,
            "captured_at": snapshot.captured_at.isoformat(),
            "entries": entries,
        }
        path = self.artifact_dir / f"{phase}_snapshot.json"
        atomic_write_text(path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        return str(path.relative_to(self.workspace))

    def load_snapshot(self, reference: str) -> ObservationSnapshot:
        snapshot, _, _ = self._load_snapshot(reference)
        return snapshot

    def _load_snapshot(
        self, reference: str
    ) -> tuple[ObservationSnapshot, dict[str, Path], Path | None]:
        path = self._workspace_path(reference)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != "forge_observation_snapshot_v1":
            raise ValueError(f"unsupported Forge snapshot: {reference}")
        images: dict[str, CapturedImage] = {}
        image_paths: dict[str, Path] = {}
        state: CapturedState | None = None
        state_path: Path | None = None
        for entry in payload.get("entries", []):
            artifact_path = self._workspace_path(str(entry["uri"]))
            data = artifact_path.read_bytes()
            received_at = datetime.fromisoformat(entry["received_at"])
            if entry["kind"] == "rgb_image":
                image = CapturedImage(
                    source_id=str(entry["source_id"]),
                    sequence=int(entry["sequence"]),
                    captured_at=entry.get("captured_at"),
                    received_at=received_at,
                    media_type=str(entry["media_type"]),
                    data=data,
                )
                images[image.source_id] = image
                image_paths[image.source_id] = artifact_path
            elif entry["kind"] == "robot_state":
                state = CapturedState(received_at, json.loads(data))
                state_path = artifact_path
        return (
            ObservationSnapshot(
                captured_at=datetime.fromisoformat(payload["captured_at"]),
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
        snapshots: dict[str, ObservationSnapshot | None] = {}
        for phase, reference in (("before", before_ref), ("after", after_ref)):
            if reference is None:
                snapshots[phase] = None
                missing.append(f"{phase}:snapshot")
                continue
            try:
                snapshot, image_paths, state_path = self._load_snapshot(reference)
                snapshots[phase] = snapshot
            except Exception as exc:
                snapshots[phase] = None
                missing.append(f"{phase}:snapshot")
                errors.append(f"{phase} snapshot invalid: {exc}")
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
        bundle = EvidenceBundle(
            bundle_id=f"forge_evidence_{uuid4().hex[:16]}",
            session_id=self.session_id,
            command_id=self.command_id,
            capture_window=EvidenceCaptureWindow(
                before_command_at=before.captured_at if before else None,
                command_terminal_at=terminal_observed_at,
                after_command_at=after.captured_at if after else None,
            ),
            artifacts=artifacts,
            quality=EvidenceQuality(
                complete=not missing,
                association_quality="best_effort",
                missing_requirements=list(dict.fromkeys(missing)),
                errors=list(dict.fromkeys(errors)),
            ),
        )
        path = self.artifact_dir / "evidence_bundle.json"
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
