import pytest
from PhyAgentOS.forge.capability_runtime import ManipulationPreparationEndpoint

from robotwin20_adapter import ReadinessAdapterError, RoboTwinReadinessEvaluator


def candidate(index=1):
    return {
        "candidate_ref": f"candidate://bottle-1/{index}",
        "entity_ref": "entity://bottle-1",
        "grasp_frame": {
            "frame_id": "camera_front",
            "unit": "m",
            "position_m": [0.1, 0.0, 0.2],
            "orientation_xyzw": [0.0, 0.0, 0.0, 1.0],
        },
        "approach_direction": {
            "frame_id": "camera_front",
            "unit": "unitless",
            "vector": [0.0, 0.0, -1.0],
        },
        "score": 0.8,
        "confidence": 0.8,
        "provenance": ["artifact://scene-7/camera_front/derived/points"],
        "qualification": "proposed",
    }


def request(**overrides):
    value = {
        "observation_ref": "observation://scene-7/camera_front",
        "scene_revision": "scene-7",
        "frame_id": "camera_front",
        "calibration_ref": "calibration://front/v3",
        "freshness_ms": 20,
        "max_age_ms": 100,
        "candidate_set_ref": "candidate-set://scene-7/camera_front",
        "candidates": [candidate(1)],
    }
    value.update(overrides)
    return value


def prepared(index=1, **overrides):
    value = {
        "candidate_ref": f"candidate://bottle-1/{index}",
        "entity_ref": "entity://bottle-1",
        "checks": {"kinematic": "pass", "collision": "pass", "workspace": "pass"},
        "evidence": [f"artifact://scene-7/camera_front/derived/readiness-{index}"],
        "qualification": "prepared",
    }
    value.update(overrides)
    return value


class Evaluator:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def evaluate(self, request):
        self.requests.append(request)
        return self.result


def test_valid_result_is_provider_neutral_and_request_isolated():
    evaluator = Evaluator({"prepared_candidates": [prepared()]})
    adapter = RoboTwinReadinessEvaluator(evaluator)
    original = request()
    result = adapter.evaluate(original)
    assert result["provider_available"] is True
    assert result["prepared_candidates"][0]["candidate_ref"] == "candidate://bottle-1/1"
    assert evaluator.requests[0] == original
    evaluator.requests[0]["scene_revision"] = "attacker"
    assert original["scene_revision"] == "scene-7"


def test_mapping_result_is_accepted_by_paos_preparation_endpoint():
    adapter = RoboTwinReadinessEvaluator(Evaluator({"prepared_candidates": [prepared()]}))
    result = ManipulationPreparationEndpoint(adapter).invoke(request())
    assert result["status"] == "available"
    assert result["motion_authorized"] is False


@pytest.mark.parametrize(
    ("result", "message"),
    [
        ({"prepared_candidates": [prepared(), prepared()]}, "unbound candidate"),
        ({"prepared_candidates": [prepared(checks={"kinematic": "pass", "collision": "pass", "workspace": "unknown"})]}, "non-passing"),
        ({"prepared_candidates": [prepared(evidence=[]) ]}, "invalid evidence"),
        ({"prepared_candidates": [prepared(candidate_ref="candidate://other/1")]}, "unbound candidate"),
        ({"prepared_candidates": [prepared(entity_ref="entity://other")]}, "unbound entity"),
        ({"prepared_candidates": [prepared(motion_authorized=True)]}, "invalid prepared candidate"),
        ({"prepared_candidates": [prepared()], "motion_authorized": True}, "provider-specific"),
    ],
)
def test_invalid_provider_results_fail_closed(result, message):
    with pytest.raises(ReadinessAdapterError, match=message):
        RoboTwinReadinessEvaluator(Evaluator(result)).evaluate(request())


@pytest.mark.parametrize(
    "payload",
    [
        request(observation_ref="observation://other/camera_front"),
        request(candidate_set_ref="candidate-set://other/camera_front"),
        request(candidates=[candidate(1), candidate(1)]),
        request(candidates=[dict(candidate(1), entity_ref="other")]),
    ],
)
def test_invalid_request_identity_fails_before_evaluator(payload):
    evaluator = Evaluator({"prepared_candidates": []})
    with pytest.raises(ReadinessAdapterError):
        RoboTwinReadinessEvaluator(evaluator).evaluate(payload)
    assert evaluator.requests == []


def test_unavailable_result_is_preserved_without_fabricating_candidates():
    result = RoboTwinReadinessEvaluator(
        Evaluator({"prepared_candidates": [], "provider_available": False})
    ).prepare(request())
    assert result == {"prepared_candidates": (), "provider_available": False}
