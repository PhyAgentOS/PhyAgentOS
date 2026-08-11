"""Build sensor frames from target observations."""

from __future__ import annotations

from typing import Any

import numpy as np

from PhyAgentOS.runtime.errors import SchemaValidationError
from PhyAgentOS.runtime.perception.config_resolver import ResolvedPerceptionPlan, sensor_by_id
from PhyAgentOS.runtime.perception.sensor_frame import SensorFrame


class SensorFrameBuilder:
    def build(self, plan: ResolvedPerceptionPlan, observation: dict[str, Any]) -> SensorFrame:
        sensors = sensor_by_id(plan.sensor_config)
        channels: dict[str, Any] = {}
        sensor_channels: dict[str, str] = {}

        for sensor_id in plan.required_sensors:
            sensor = sensors[sensor_id]
            value = self._get_observation_value(observation, sensor.observation_key)
            if value is None:
                raise SchemaValidationError(
                    f"observation channel missing for sensor {sensor_id}: {sensor.observation_key}"
                )
            schema = plan.sensor_config.observation_schema.get(sensor.observation_key)
            if schema is not None:
                self._check_channel(sensor_id, sensor.observation_key, value, schema.dtype, schema.shape)
            channels[sensor.observation_key] = value
            sensor_channels[sensor_id] = sensor.observation_key

        return SensorFrame(
            target_id=plan.target_id,
            session_id=plan.session_id,
            channels=channels,
            sensor_channels=sensor_channels,
        )

    def _get_observation_value(self, observation: dict[str, Any], key: str) -> Any:
        if key in observation:
            return observation[key]
        value: Any = observation
        for part in key.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None
        return value

    def _check_channel(
        self,
        sensor_id: str,
        observation_key: str,
        value: Any,
        dtype: str,
        shape: list[int | None],
    ) -> None:
        array = np.asarray(value)
        if dtype and str(array.dtype) != dtype:
            raise SchemaValidationError(
                f"observation channel {observation_key} for sensor {sensor_id} has dtype {array.dtype}, expected {dtype}"
            )
        if shape and len(array.shape) != len(shape):
            raise SchemaValidationError(
                f"observation channel {observation_key} for sensor {sensor_id} has shape {array.shape}, expected {shape}"
            )
        for idx, expected in enumerate(shape):
            if expected is not None and array.shape[idx] != expected:
                raise SchemaValidationError(
                    f"observation channel {observation_key} for sensor {sensor_id} has shape {array.shape}, expected {shape}"
                )

