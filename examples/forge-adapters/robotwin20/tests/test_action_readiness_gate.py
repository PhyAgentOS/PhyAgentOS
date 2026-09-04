from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PhyAgentOS.forge.tool_client import ForgeToolAPIError, ForgeToolClient
from pick_place_workflow.fake_gateway import FakeGatewayTransport
from pick_place_workflow.object_acquire import AcquireSnapshot
from pick_place_workflow.object_place import PlaceSnapshot

from robotwin20_adapter.action_readiness import (
    ReadinessEvidenceGate,
    build_action_readiness_gate,
)

IDENTITY = {
    "observation_ref": "observation://scene-7/camera_front",
    "scene_revision": "scene-7",
    "frame_id": "camera_front",
    "calibration_ref": "artifact://scene-7/capture/calibration",
    "candidate_set_ref": "candidate-set://scene-7/camera_front",
}
CANDIDATE = "candidate://bottle-1/1"
ENTITY = "entity://bottle-1"
WORKER_ID = "robotwin20-readiness-live/v1"
EMBODIMENT = {
    "robot_identity": "franka-panda",
    "gripper_identity": "panda-gripper",
    "embodiment_topology": "two-single-arm",
    "planner_profile": "curobo",
    "profile_digest": "a" * 64,
}


def _write_reviewed_evidence(root: Path, *, motion_authorized: bool = False) -> tuple[Path, Path]:
    evidence_ref = "artifact://scene-7/capture/derived/readiness-1"
    evidence_path = root / "scene-7" / "capture" / "derived" / "readiness-1.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "paos-robotwin20-readiness-evidence/v1",
                **IDENTITY,
                "candidate_ref": CANDIDATE,
                "entity_ref": ENTITY,
                "checks": {"kinematic": "pass", "collision": "pass", "workspace": "pass"},
                "motion_authorized": motion_authorized,
                "worker_id": WORKER_ID,
                "embodiment_binding": EMBODIMENT,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    manifest_path = root / "manifest.json"
    manifest = {
        "schema_version": "paos-robotwin20-readiness-evidence-manifest/v2",
        "motion_authorized": False,
        "worker_id": WORKER_ID,
        "embodiment_binding": EMBODIMENT,
        "artifacts": [
            {
                **IDENTITY,
                "candidate_ref": CANDIDATE,
                "entity_ref": ENTITY,
                "artifact_ref": evidence_ref,
                "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            }
        ],
    }
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    review_path = root / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "schema_version": "paos-robotwin20-readiness-manual-review/v2",
                "decision": "approved_readiness_evidence_for_next_no_motion_gate",
                "request_identity": IDENTITY,
                "summary": {
                    "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                    "motion_authorized_false": True,
                    "all_checks_pass": True,
                    "binding_match": True,
                    "identity_bound": True,
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return manifest_path, review_path


def _acquire_request(**overrides):
    value = {
        **IDENTITY,
        "freshness_ms": 10,
        "max_age_ms": 100,
        "preparation_ref": "preparation://scene-7/camera_front",
        "candidate_ref": CANDIDATE,
        "entity_ref": ENTITY,
    }
    value.update(overrides)
    return value


def _place_request(acquire_invocation_ref: str, **overrides):
    value = {
        **_acquire_request(),
        "acquire_invocation_ref": acquire_invocation_ref,
        "destination_ref": "destination://bin/primary",
    }
    value.update(overrides)
    return value


class AcquireProvider:
    def __init__(self):
        self.calls = 0

    def acquire(self, request):
        self.calls += 1
        return AcquireSnapshot(
            world_change_started=False,
            evidence_availability="none",
            status="succeeded",
            capability_phase="none",
        )


class PlaceProvider:
    def place(self, request):
        return PlaceSnapshot(
            world_change_started=False,
            evidence_availability="none",
            post_release_evidence_availability="none",
            status="succeeded",
            capability_phase="none",
        )


def test_gate_loads_reviewed_no_motion_evidence(tmp_path):
    manifest, review = _write_reviewed_evidence(tmp_path)
    gate = ReadinessEvidenceGate.from_files(manifest, review)
    assert gate.check(_acquire_request()) is None
    assert gate.candidate_refs == frozenset({CANDIDATE})


def test_profile_builder_keeps_paths_external_and_validates_review(tmp_path):
    manifest, review = _write_reviewed_evidence(tmp_path)
    profile = tmp_path / "action-readiness.yaml"
    profile.write_text(
        "schema_version: paos-robotwin20-action-readiness/v1\n"
        "manifest: ${MANIFEST}\n"
        "manual_review: ${REVIEW}\n"
        "artifact_root: ${ROOT}\n",
        encoding="utf-8",
    )
    gate = build_action_readiness_gate(
        profile,
        environ={"MANIFEST": str(manifest), "REVIEW": str(review), "ROOT": str(tmp_path)},
    )
    assert gate.check(_acquire_request()) is None


def test_profile_builder_rejects_symlinked_evidence_paths(tmp_path):
    manifest, review = _write_reviewed_evidence(tmp_path)
    profile_root = tmp_path / "profile"
    profile_root.mkdir()
    linked_manifest = profile_root / "manifest.json"
    linked_manifest.symlink_to(manifest)
    profile = profile_root / "action-readiness.yaml"
    profile.write_text(
        "schema_version: paos-robotwin20-action-readiness/v1\n"
        f"manifest: {linked_manifest}\n"
        f"manual_review: {review}\n"
        f"artifact_root: {tmp_path}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must not be a symlink"):
        build_action_readiness_gate(profile)


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"scene_revision": "scene-8"}, "readiness_identity_mismatch"),
        ({"candidate_ref": "candidate://bottle-1/2"}, "readiness_evidence_missing"),
        ({"entity_ref": "entity://cup-1"}, "readiness_entity_mismatch"),
        ({"freshness_ms": 101}, "stale_observation"),
    ],
)
def test_gate_rejects_identity_drift_before_action(tmp_path, override, code):
    manifest, review = _write_reviewed_evidence(tmp_path)
    gate = ReadinessEvidenceGate.from_files(manifest, review)
    assert gate.check(_acquire_request(**override)) == code


@pytest.mark.asyncio
async def test_gateway_action_is_admitted_only_after_reviewed_readiness_and_stays_no_motion(tmp_path):
    manifest, review = _write_reviewed_evidence(tmp_path)
    gate = ReadinessEvidenceGate.from_files(manifest, review)
    provider = AcquireProvider()
    transport = FakeGatewayTransport(
        type("Observation", (), {"observe": lambda self, sensor_ref: None})(),
        acquire_provider=provider,
        readiness_gate=gate,
    )
    async with ForgeToolClient("http://fake", transport=transport) as client:
        context = await client.get_tool_context("object.acquire")
        accepted = await client.invoke_action("object.acquire", _acquire_request())
        result = await client.invocation_result(accepted["data"]["invocation_id"])
        with pytest.raises(ForgeToolAPIError) as excinfo:
            await client.invoke_action("object.acquire", _acquire_request(candidate_ref="candidate://bottle-1/2"))
    assert context["data"]["motion_authorized"] is False
    assert result["data"]["result"]["capability_outcome_summary"]["world_change_started"] is False
    assert provider.calls == 1
    assert excinfo.value.error_code == "readiness_evidence_missing"
    assert len(transport.invocations) == 1


def test_manifest_rejects_motion_enabled_evidence(tmp_path):
    manifest, review = _write_reviewed_evidence(tmp_path, motion_authorized=True)
    with pytest.raises(ValueError, match="must be no-motion"):
        ReadinessEvidenceGate.from_files(manifest, review)


@pytest.mark.asyncio
async def test_no_motion_gate_rejects_provider_that_reports_world_change(tmp_path):
    manifest, review = _write_reviewed_evidence(tmp_path)
    gate = ReadinessEvidenceGate.from_files(manifest, review)

    class MovingProvider(AcquireProvider):
        def acquire(self, request):
            return AcquireSnapshot(
                world_change_started=True,
                evidence_availability="partial",
                artifact_refs=("artifact://unsafe/motion",),
                status="succeeded",
                capability_phase="hold",
            )

    transport = FakeGatewayTransport(
        type("Observation", (), {"observe": lambda self, sensor_ref: None})(),
        acquire_provider=MovingProvider(),
        readiness_gate=gate,
    )
    async with ForgeToolClient("http://fake", transport=transport) as client:
        with pytest.raises(ForgeToolAPIError) as excinfo:
            await client.invoke_action("object.acquire", _acquire_request())
    assert excinfo.value.error_code == "motion_started_in_no_motion_mode"
    assert transport.invocations == {}


@pytest.mark.asyncio
async def test_place_action_reuses_the_same_reviewed_gate_and_acquire_identity(tmp_path):
    manifest, review = _write_reviewed_evidence(tmp_path)
    gate = ReadinessEvidenceGate.from_files(manifest, review)
    transport = FakeGatewayTransport(
        type("Observation", (), {"observe": lambda self, sensor_ref: None})(),
        acquire_provider=AcquireProvider(),
        place_provider=PlaceProvider(),
        readiness_gate=gate,
    )
    async with ForgeToolClient("http://fake", transport=transport) as client:
        acquired = await client.invoke_action("object.acquire", _acquire_request())
        acquire_ref = acquired["data"]["invocation_id"]
        await client.invocation_result(acquire_ref)
        placed = await client.invoke_action("object.place", _place_request(acquire_ref))
        result = await client.invocation_result(placed["data"]["invocation_id"])
    assert result["data"]["result"]["capability_outcome_summary"]["world_change_started"] is False


@pytest.mark.asyncio
async def test_deferred_gateway_starts_provider_only_after_invocation_allocation(tmp_path):
    manifest, review = _write_reviewed_evidence(tmp_path)
    gate = ReadinessEvidenceGate.from_files(manifest, review)
    provider = AcquireProvider()
    transport = FakeGatewayTransport(
        type("Observation", (), {"observe": lambda self, sensor_ref: None})(),
        acquire_provider=provider,
        readiness_gate=gate,
        defer_action_execution=True,
    )
    async with ForgeToolClient("http://fake", transport=transport) as client:
        accepted = await client.invoke_action("object.acquire", _acquire_request())
        invocation_id = accepted["data"]["invocation_id"]
        assert provider.calls == 0
        assert invocation_id in transport.invocations
        result = await client.invocation_result(invocation_id)
    assert provider.calls == 1
    assert result["data"]["result"]["status"] == "succeeded"
    assert transport.invocations[invocation_id]["started"] is True


@pytest.mark.asyncio
async def test_deferred_gateway_cancel_before_first_poll_never_starts_provider(tmp_path):
    manifest, review = _write_reviewed_evidence(tmp_path)
    gate = ReadinessEvidenceGate.from_files(manifest, review)
    provider = AcquireProvider()
    transport = FakeGatewayTransport(
        type("Observation", (), {"observe": lambda self, sensor_ref: None})(),
        acquire_provider=provider,
        readiness_gate=gate,
        defer_action_execution=True,
    )
    async with ForgeToolClient("http://fake", transport=transport) as client:
        accepted = await client.invoke_action("object.acquire", _acquire_request())
        invocation_id = accepted["data"]["invocation_id"]
        await client.cancel_invocation(invocation_id)
        result = await client.invocation_result(invocation_id)
    assert provider.calls == 0
    assert result["data"]["result"]["status"] == "cancelled"
    assert transport.invocations[invocation_id]["started"] is False


@pytest.mark.asyncio
async def test_deferred_gateway_provider_start_failure_is_a_bound_terminal_failure(tmp_path):
    manifest, review = _write_reviewed_evidence(tmp_path)
    gate = ReadinessEvidenceGate.from_files(manifest, review)

    class FailingProvider:
        def acquire(self, request):
            raise RuntimeError("simulated provider start failure")

    transport = FakeGatewayTransport(
        type("Observation", (), {"observe": lambda self, sensor_ref: None})(),
        acquire_provider=FailingProvider(),
        readiness_gate=gate,
        defer_action_execution=True,
    )
    async with ForgeToolClient("http://fake", transport=transport) as client:
        accepted = await client.invoke_action("object.acquire", _acquire_request())
        invocation_id = accepted["data"]["invocation_id"]
        result = await client.invocation_result(invocation_id)
    assert result["data"]["result"]["status"] == "failed"
    assert result["data"]["result"]["capability_outcome_summary"]["failure_code"] == "acquire_provider_error"
