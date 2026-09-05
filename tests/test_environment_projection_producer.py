from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from PhyAgentOS.forge import (
    EnvironmentProjectionInput,
    EnvironmentProjectionProducer,
    EnvironmentProjectionProducerError,
)
from PhyAgentOS.forge.evidence import ForgeEvidenceWriter
from PhyAgentOS.forge.observation import CapturedImage, ObservationSnapshot
from PhyAgentOS.state_io import StateFileDriftError, parse_environment_projection

CAPTURED_AT = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)


def _snapshot(*, empty: bool = False) -> ObservationSnapshot:
    if empty:
        return ObservationSnapshot(captured_at=CAPTURED_AT)
    image = CapturedImage(
        source_id="camera/front",
        sequence=4,
        captured_at=CAPTURED_AT.timestamp(),
        received_at=CAPTURED_AT,
        media_type="image/png",
        data=b"fake-rgb",
    )
    return ObservationSnapshot(captured_at=CAPTURED_AT, images={"camera/front": image})


def _metadata(**overrides):
    value = {
        "scene_revision": "scene-4",
        "snapshot_ref": "evidence://agent-task/task-4/before_snapshot",
        "phase": "before",
        "source_id": "sensor://camera/front",
        "frame": "world",
        "calibration_ref": "calibration://camera/front/v4",
        "scene_graph": {"nodes": [], "relations": []},
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize("phase", ["before", "after"])
def test_producer_renders_projection_from_observation_snapshot(tmp_path, phase):
    path = tmp_path / "ENVIRONMENT.md"
    result = EnvironmentProjectionProducer().publish(
        path,
        _snapshot(),
        EnvironmentProjectionInput(
            **_metadata(
                phase=phase,
                snapshot_ref=f"evidence://agent-task/task-4/{phase}_snapshot",
            )
        ),
    )

    parsed = parse_environment_projection(path)
    assert result.changed is True
    assert parsed.data.scene_revision == "scene-4"
    assert parsed.data.snapshot_ref == f"evidence://agent-task/task-4/{phase}_snapshot"
    assert parsed.data.captured_at == CAPTURED_AT.isoformat()
    assert parsed.source.source.startswith("producer://")


def test_producer_is_idempotent_and_supports_drift_guard(tmp_path):
    path = tmp_path / "ENVIRONMENT.md"
    producer = EnvironmentProjectionProducer()
    first = producer.publish(path, _snapshot(), _metadata())
    second = producer.publish(
        path,
        _snapshot(),
        _metadata(),
        expected_sha256=first.data_sha256,
    )
    assert second.changed is False
    with pytest.raises(StateFileDriftError, match="projection drift"):
        producer.publish(
            path,
            _snapshot(),
            _metadata(scene_graph={"nodes": [{"id": "cup"}], "relations": []}),
            expected_sha256="0" * 64,
        )


def test_producer_rejects_empty_observation_and_invalid_metadata(tmp_path):
    producer = EnvironmentProjectionProducer()
    with pytest.raises(EnvironmentProjectionProducerError, match="at least one"):
        producer.publish(tmp_path / "ENVIRONMENT.md", _snapshot(empty=True), _metadata())
    with pytest.raises(EnvironmentProjectionProducerError, match="invalid environment projection schema"):
        producer.publish(
            tmp_path / "ENVIRONMENT.md",
            _snapshot(),
            _metadata(scene_revision=""),
        )
    assert not (tmp_path / "ENVIRONMENT.md").exists()


def test_before_after_projection_requires_evidence_snapshot_reference(tmp_path):
    path = tmp_path / "ENVIRONMENT.md"
    with pytest.raises(EnvironmentProjectionProducerError, match="evidence://"):
        EnvironmentProjectionProducer().publish(
            path,
            _snapshot(),
            _metadata(snapshot_ref="observation://scene-4/camera-front"),
        )
    assert not path.exists()


def test_publish_from_adapter_binds_revision_without_capture_or_action(tmp_path):
    class Adapter:
        def __init__(self):
            self.snapshot_calls = 0

        def snapshot(self):
            self.snapshot_calls += 1
            return {"scene_revision": "scene-4", "status": "ready"}

        def capture(self):
            raise AssertionError("producer must not capture sensors")

    adapter = Adapter()
    path = tmp_path / "ENVIRONMENT.md"
    EnvironmentProjectionProducer().publish_from_adapter(
        path, adapter, _snapshot(), _metadata()
    )
    assert adapter.snapshot_calls == 1
    assert json.loads(path.read_text(encoding="utf-8").split("```json\n", 1)[1].split("\n```", 1)[0])["paos"]["mode"] == "projection"


def test_publish_from_adapter_rejects_revision_mismatch_without_writing(tmp_path):
    class Adapter:
        def snapshot(self):
            return {"scene_revision": "scene-other"}

    path = tmp_path / "ENVIRONMENT.md"
    with pytest.raises(EnvironmentProjectionProducerError, match="does not match"):
        EnvironmentProjectionProducer().publish_from_adapter(
            path, Adapter(), _snapshot(), _metadata()
        )
    assert not path.exists()


def test_publish_from_evidence_writer_derives_phase_and_opaque_reference(tmp_path):
    writer = ForgeEvidenceWriter(tmp_path, "task-4", "command-1")
    snapshot_reference = writer.write_snapshot("after", _snapshot())
    metadata = _metadata()
    metadata.pop("phase")
    metadata.pop("snapshot_ref")
    metadata["scene_revision"] = "scene-4"

    output = tmp_path / "ENVIRONMENT.md"
    EnvironmentProjectionProducer().publish_from_evidence_writer(
        output, writer, snapshot_reference, metadata
    )
    parsed = parse_environment_projection(output)
    assert parsed.data.phase == "after"
    assert parsed.data.snapshot_ref.startswith(
        "evidence://forge/task-4/after_snapshot/"
    )
    assert len(parsed.data.snapshot_ref.rsplit("/", 1)[1]) == 64


def test_evidence_writer_rejects_snapshot_rewrite_and_projection_mismatch(tmp_path):
    writer = ForgeEvidenceWriter(tmp_path, "task-4", "command-1")
    reference = writer.write_snapshot("before", _snapshot())
    projection_ref = writer.snapshot_projection_ref(reference)
    assert projection_ref.startswith("evidence://forge/task-4/before_snapshot/")
    assert len(projection_ref.rsplit("/", 1)[1]) == 64
    writer.write_snapshot("before", _snapshot())
    changed = replace(
        _snapshot().images["camera/front"],
        data=b"changed-rgb",
    )
    with pytest.raises(ValueError, match="immutable before"):
        writer.write_snapshot(
            "before",
            ObservationSnapshot(captured_at=CAPTURED_AT, images={"camera/front": changed}),
        )
    with pytest.raises(EnvironmentProjectionProducerError, match="does not match"):
        EnvironmentProjectionProducer().publish_from_evidence_writer(
            tmp_path / "ENVIRONMENT.md",
            writer,
            reference,
            _metadata(phase="after", snapshot_ref="evidence://forge/task-4/after_snapshot"),
        )


def test_publish_from_evidence_writer_rejects_non_writer_reference(tmp_path):
    writer = ForgeEvidenceWriter(tmp_path, "task-4", "command-1")
    with pytest.raises(EnvironmentProjectionProducerError, match="invalid Forge evidence"):
        EnvironmentProjectionProducer().publish_from_evidence_writer(
            tmp_path / "ENVIRONMENT.md", writer, "artifacts/other.json", _metadata()
        )
