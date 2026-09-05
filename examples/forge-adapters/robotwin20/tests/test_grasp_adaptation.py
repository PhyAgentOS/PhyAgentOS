from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from robotwin20_adapter.grasp_adaptation import (
    GRASP_ADAPTATION_PROFILE_SCHEMA_VERSION,
    GraspAdaptationError,
    adapt_grasp_candidate,
    camera_pose_to_world_matrix,
)


def _inputs():
    calibration = {
        "camera_name": "head_camera",
        # SAPIEN OpenCV extrinsic: world -> camera.
        "extrinsic_cv": [[1, 0, 0, -1], [0, 1, 0, -2], [0, 0, 1, -3]],
    }
    payload = json.dumps(calibration, separators=(",", ":")).encode()
    base = {
        "observation_ref": "observation://scene-1/head_camera",
        "observation_frame_id": "head_camera",
        "scene_revision": "scene-1",
        "frame_id": "world",
        "calibration_ref": "artifact://scene/calibration",
        "calibration_sha256": hashlib.sha256(payload).hexdigest(),
        "calibration_revision": "calibration-1",
        "candidate_set_ref": "candidate-set://scene-1/head_camera",
    }
    proposal = {
        "candidate_ref": "candidate://block/1",
        "entity_ref": "entity://block",
        "grasp_frame": {
            "frame_id": "head_camera",
            "unit": "m",
            "position_m": [0.1, 0.2, 0.3],
            "orientation_xyzw": [0, 0, 0, 1],
        },
        "approach_direction": {
            "frame_id": "head_camera", "unit": "unitless", "vector": [0, 0, 1]
        },
        "score": 0.9,
        "confidence": 0.9,
        "provenance": ["artifact://scene/points"],
        "qualification": "proposed",
    }
    profile = {
        "schema_version": GRASP_ADAPTATION_PROFILE_SCHEMA_VERSION,
        "extrinsic_semantics": "world_to_camera_cv",
        "provider_T_tcp": [1, 0, 0, 0.01, 0, 1, 0, 0.02, 0, 0, 1, 0.03, 0, 0, 0, 1],
        "adaptation_provenance_ref": "artifact://profile/provider-to-tcp",
        "support_clear_direction": {
            "frame_id": "world", "vector": [0, 0, 1],
            "provenance_ref": "artifact://profile/support-normal",
        },
        "max_linear_speed_mps": 0.2,
        "max_joint_speed_radps": 1.0,
    }
    return proposal, payload, base, profile


def test_adaptation_inverts_world_to_camera_and_applies_tool_transform():
    result = adapt_grasp_candidate(*_inputs())
    assert result["contact_tcp_pose"]["position_m"] == pytest.approx([1.11, 2.22, 3.33])
    assert result["contact_tcp_pose"]["orientation_xyzw"] == pytest.approx([0, 0, 0, 1])
    assert result["ingress_direction"]["vector"] == pytest.approx([0, 0, 1])


def test_camera_pose_to_world_matrix_uses_inverse_extrinsic():
    proposal, payload, base, _ = _inputs()
    calibration = json.loads(payload)
    matrix = camera_pose_to_world_matrix(
        proposal["grasp_frame"], calibration, base["observation_frame_id"]
    )
    assert [matrix[index][3] for index in range(3)] == pytest.approx([1.1, 2.2, 3.3])


def test_adaptation_is_deterministic_and_does_not_mutate_inputs():
    inputs = _inputs()
    before = deepcopy(inputs)
    assert adapt_grasp_candidate(*inputs) == adapt_grasp_candidate(*inputs)
    assert inputs == before


@pytest.mark.parametrize(
    ("index", "mutate", "message"),
    [
        (2, lambda value: value.update(calibration_sha256="0" * 64), "digest"),
        (2, lambda value: value.update(frame_id="head_camera"), "world route frame"),
        (3, lambda value: value.update(extrinsic_semantics="camera_to_world"), "semantics"),
        (3, lambda value: value.update(provider_T_tcp=[0] * 16), "homogeneous row"),
        (0, lambda value: value["grasp_frame"].update(frame_id="wrist"), "binding"),
        (0, lambda value: value["approach_direction"].update(vector=[0, 0, 0]), "degenerate"),
    ],
)
def test_adaptation_fails_closed_on_untrusted_binding(index, mutate, message):
    inputs = list(_inputs())
    mutate(inputs[index])
    with pytest.raises(GraspAdaptationError, match=message):
        adapt_grasp_candidate(*inputs)
