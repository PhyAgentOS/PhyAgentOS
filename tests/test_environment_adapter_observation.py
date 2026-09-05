from datetime import datetime, timezone

import pytest

from PhyAgentOS.forge.capability_runtime import (
    OBSERVATION_TOOL_SPEC,
    CapabilityRuntime,
    ObservationContractError,
    ObservationEndpoint,
)


class Source:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def capture(self, request):
        self.calls += 1
        return self.value


class FailingSource:
    def capture(self, request):
        raise RuntimeError("private provider detail")


def observation(**overrides):
    value = {
        "captured_at": datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc),
        "scene_revision": "scene-1",
        "frame_id": "camera-front",
        "calibration_ref": "calibration://front/v1",
        "artifacts": [{"ref": "artifact://scene-1/rgb", "kind": "rgb", "media_type": "image/jpeg"}],
    }
    value.update(overrides)
    return value


def test_observation_endpoint_projects_adapter_capture_and_freshness():
    source = Source(observation())
    endpoint = ObservationEndpoint(
        source,
        now=lambda: datetime(2026, 9, 4, 0, 0, 0, 500000, tzinfo=timezone.utc),
    )
    result = endpoint.invoke({"sensor_ref": "camera/front", "max_age_ms": 1000})
    assert result["status"] == "available"
    assert result["observation_ref"] == "observation://scene-1/camera-front"
    assert result["freshness_ms"] == 500
    assert source.calls == 1


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (observation(calibration_ref=None), "missing_calibration"),
        (observation(observation_ref="observation://other/frame"), "invalid_observation_binding"),
        (observation(artifacts=[]), "missing_artifacts"),
        (observation(artifacts=[{"ref": "actor://truth", "kind": "state", "media_type": "application/json"}]), "invalid_artifact"),
        (observation(sensor_available=False), "sensor_unavailable"),
    ],
)
def test_observation_endpoint_fails_closed_on_untrusted_adapter_payload(value, code):
    result = ObservationEndpoint(Source(value)).invoke({"sensor_ref": "camera/front", "max_age_ms": 1000})
    assert result["status"] == ("invalid" if code.startswith("invalid") else "unavailable")
    assert result["error"]["code"] == code


def test_observation_endpoint_rejects_invalid_input_before_source_call():
    source = Source(observation())
    result = ObservationEndpoint(source).invoke({"sensor_ref": "", "max_age_ms": 1000})
    assert result["error"]["code"] == "invalid_sensor_ref"
    assert source.calls == 0


def test_observation_endpoint_maps_provider_failure_to_private_unavailable_result():
    def clock():
        return datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc)

    result = ObservationEndpoint(FailingSource(), now=clock).invoke(
        {"sensor_ref": "camera/front", "max_age_ms": 1000}
    )
    assert result["status"] == "unavailable"
    assert result["error"] == {
        "code": "sensor_unavailable",
        "message": "observation source failed",
    }
    assert "private provider detail" not in str(result)


def test_observation_tool_spec_registers_explicitly_without_hidden_provider_wiring():
    runtime = CapabilityRuntime()
    runtime.register_tool(
        OBSERVATION_TOOL_SPEC,
        ObservationEndpoint(
            Source(observation()),
            now=lambda: datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc),
        ),
    )
    assert runtime.get_tool("scene.observe")["endpoint_id"] == "scene_observation"
    result = runtime.invoke_query("scene_observation", "observe", {
        "sensor_ref": "camera/front", "max_age_ms": 1000,
    })
    assert result["status"] == "available"


def test_error_projection_uses_injected_clock_and_rejects_naive_clock():
    fixed = datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc)
    result = ObservationEndpoint(Source(None), now=lambda: fixed).invoke(
        {"sensor_ref": "camera/front", "max_age_ms": 1000}
    )
    assert result["captured_at"] == "2026-09-04T00:00:00Z"
    with pytest.raises(ObservationContractError, match="timezone-aware"):
        ObservationEndpoint(Source(None), now=lambda: datetime(2026, 9, 4)).invoke(
            {"sensor_ref": "camera/front", "max_age_ms": 1000}
        )
