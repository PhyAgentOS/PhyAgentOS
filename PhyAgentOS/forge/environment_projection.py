"""Produce the non-authoritative ENVIRONMENT.md projection.

The producer is deliberately downstream of observation/evidence capture.  It
accepts an immutable ``ObservationSnapshot`` plus explicit scene metadata and
only writes the human-readable projection.  It never captures sensors, calls a
Gateway, creates an AgentTask, or grants Action admission.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol

from PhyAgentOS.forge.capability_runtime.ports import EnvironmentAdapter
from PhyAgentOS.forge.observation import ObservationSnapshot
from PhyAgentOS.state_io.adapters import render_environment_projection
from PhyAgentOS.state_io.protocol import (
    ProjectionResult,
    StateFileDriftError,
    StateFileError,
)


class EnvironmentProjectionProducerError(StateFileError):
    """Raised when a snapshot cannot be safely projected."""


class EvidenceSnapshotStore(Protocol):
    """Minimal writer seam used for snapshot association."""

    def load_snapshot(self, reference: str) -> ObservationSnapshot: ...

    def snapshot_projection_identity(self, reference: str) -> tuple[str, str]: ...


@dataclass(frozen=True)
class EnvironmentProjectionInput:
    """Explicit provenance supplied by an observation/scene provider.

    Provider-specific scene objects stay inside ``scene_graph`` and its
    optional projections.  The producer does not infer them from simulator
    state or from image bytes.
    """

    scene_revision: str
    snapshot_ref: str
    phase: Literal["before", "after", "live"]
    source_id: str
    frame: str
    calibration_ref: str
    scene_graph: dict[str, Any]
    objects: dict[str, Any] | None = None
    robots: dict[str, Any] | None = None
    map: dict[str, Any] | None = None

    def as_mapping(self, captured_at: str) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": "paos.environment.v1",
            "scene_revision": self.scene_revision,
            "snapshot_ref": self.snapshot_ref,
            "phase": self.phase,
            "captured_at": captured_at,
            "source_id": self.source_id,
            "frame": self.frame,
            "calibration_ref": self.calibration_ref,
            "scene_graph": self.scene_graph,
        }
        for name, value in (
            ("objects", self.objects),
            ("robots", self.robots),
            ("map", self.map),
        ):
            if value is not None:
                data[name] = value
        return data


class EnvironmentProjectionProducer:
    """Render an ENVIRONMENT projection from an already captured snapshot."""

    def __init__(self, *, source: str = "producer://paos/environment/v1") -> None:
        self.source = source

    def publish(
        self,
        path: str | Path,
        snapshot: ObservationSnapshot,
        metadata: EnvironmentProjectionInput | Mapping[str, Any],
        *,
        expected_sha256: str | None = None,
    ) -> ProjectionResult:
        if not isinstance(snapshot, ObservationSnapshot):
            raise EnvironmentProjectionProducerError(
                "environment projection requires an ObservationSnapshot"
            )
        if not snapshot.images and snapshot.state is None:
            raise EnvironmentProjectionProducerError(
                "environment projection requires at least one captured sensor artifact"
            )
        captured_at = snapshot.captured_at
        if not isinstance(captured_at, datetime) or captured_at.tzinfo is None:
            raise EnvironmentProjectionProducerError(
                "observation snapshot captured_at must include a timezone"
            )
        input_data = self._normalize_input(metadata)
        if input_data.phase in {"before", "after"} and not input_data.snapshot_ref.lower().startswith(
            "evidence://"
        ):
            raise EnvironmentProjectionProducerError(
                "before/after environment projections require an evidence:// snapshot_ref"
            )
        data = input_data.as_mapping(captured_at.isoformat())
        try:
            return render_environment_projection(
                path,
                data,
                revision=input_data.scene_revision,
                source=self.source,
                expected_sha256=expected_sha256,
            )
        except StateFileDriftError:
            raise
        except StateFileError as exc:
            raise EnvironmentProjectionProducerError(str(exc)) from exc

    def publish_from_adapter(
        self,
        path: str | Path,
        adapter: EnvironmentAdapter,
        snapshot: ObservationSnapshot,
        metadata: EnvironmentProjectionInput | Mapping[str, Any],
        *,
        expected_sha256: str | None = None,
    ) -> ProjectionResult:
        """Bind projection revision to the adapter's sanitized identity only."""

        input_data = self._normalize_input(metadata)
        adapter_snapshot = getattr(adapter, "snapshot", None)
        if not callable(adapter_snapshot):
            raise EnvironmentProjectionProducerError(
                "environment adapter must expose snapshot()"
            )
        identity = adapter_snapshot()
        if not isinstance(identity, Mapping):
            raise EnvironmentProjectionProducerError(
                "environment adapter snapshot must be an object"
            )
        adapter_revision = identity.get("scene_revision")
        if not isinstance(adapter_revision, str) or not adapter_revision.strip():
            raise EnvironmentProjectionProducerError(
                "environment adapter snapshot lacks scene_revision"
            )
        if input_data.scene_revision != adapter_revision:
            raise EnvironmentProjectionProducerError(
                "environment projection revision does not match adapter snapshot"
            )
        return self.publish(
            path,
            snapshot,
            input_data,
            expected_sha256=expected_sha256,
        )

    def publish_from_evidence_writer(
        self,
        path: str | Path,
        writer: EvidenceSnapshotStore,
        snapshot_reference: str,
        metadata: EnvironmentProjectionInput | Mapping[str, Any],
        *,
        expected_sha256: str | None = None,
    ) -> ProjectionResult:
        """Associate a writer-owned immutable snapshot with a projection.

        ``phase`` and ``snapshot_ref`` are derived from the writer manifest. If
        callers provide either field, it must match the derived identity.
        """

        try:
            phase, evidence_ref = writer.snapshot_projection_identity(snapshot_reference)
            snapshot = writer.load_snapshot(snapshot_reference)
        except Exception as exc:
            raise EnvironmentProjectionProducerError(
                f"invalid Forge evidence snapshot reference: {exc}"
            ) from exc
        if isinstance(metadata, EnvironmentProjectionInput):
            if metadata.phase != phase or metadata.snapshot_ref != evidence_ref:
                raise EnvironmentProjectionProducerError(
                    "environment metadata does not match evidence snapshot identity"
                )
            input_data = metadata
        elif isinstance(metadata, Mapping):
            supplied = dict(metadata)
            for name, expected in (("phase", phase), ("snapshot_ref", evidence_ref)):
                if name in supplied and supplied[name] != expected:
                    raise EnvironmentProjectionProducerError(
                        f"environment metadata {name} does not match evidence snapshot identity"
                    )
                supplied[name] = expected
            input_data = self._normalize_input(supplied)
        else:
            raise EnvironmentProjectionProducerError(
                "environment projection metadata must be an object"
            )
        return self.publish(
            path,
            snapshot,
            input_data,
            expected_sha256=expected_sha256,
        )

    @staticmethod
    def _normalize_input(
        metadata: EnvironmentProjectionInput | Mapping[str, Any],
    ) -> EnvironmentProjectionInput:
        if isinstance(metadata, EnvironmentProjectionInput):
            return metadata
        if not isinstance(metadata, Mapping):
            raise EnvironmentProjectionProducerError(
                "environment projection metadata must be an object"
            )
        try:
            return EnvironmentProjectionInput(**dict(metadata))
        except (TypeError, ValueError) as exc:
            raise EnvironmentProjectionProducerError(
                "invalid environment projection producer metadata"
            ) from exc


__all__ = [
    "EnvironmentProjectionInput",
    "EnvironmentProjectionProducer",
    "EnvironmentProjectionProducerError",
    "EvidenceSnapshotStore",
]
