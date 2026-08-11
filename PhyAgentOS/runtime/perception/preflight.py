"""Strict perception preflight checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx

from PhyAgentOS.runtime.errors import SchemaValidationError
from PhyAgentOS.runtime.perception.config_resolver import (
    PerceptionConfigResolver,
    ResolvedPerceptionPlan,
    sensor_by_id,
)
from PhyAgentOS.runtime.perception.diagnostics import PreflightResult
from PhyAgentOS.runtime.schemas.perception import PerceptionModelSpec


class PerceptionPreflightError(SchemaValidationError):
    """Raised when strict perception preflight rejects a session."""


class PerceptionPreflightChecker:
    def __init__(self, workspace: Path, resolver: PerceptionConfigResolver | None = None):
        self.workspace = workspace
        self.resolver = resolver or PerceptionConfigResolver(workspace)

    def check(self, plan: ResolvedPerceptionPlan) -> None:
        result = PreflightResult(session_id=plan.session_id)
        sensors = sensor_by_id(plan.sensor_config)
        sensor_config_path = self.resolver.resolve_path(plan.sensor_config_ref)
        perception_config_path = (
            self.resolver.resolve_path(plan.perception_config_ref)
            if plan.perception_config_ref
            else None
        )

        for sensor_id in plan.required_sensors:
            sensor = sensors.get(sensor_id)
            if sensor is None:
                result.add(
                    "sensor_config_missing",
                    f"{sensor_config_path} sensors[{sensor_id}]",
                    f"enabled sensor id {sensor_id}",
                    "Add the sensor to sensor_config_ref or remove it from skill requirements.",
                )
                continue
            if not sensor.enabled:
                result.add(
                    "sensor_disabled",
                    f"{sensor_config_path} sensors[{sensor_id}].enabled",
                    "true",
                    "Enable the sensor or choose a target with this sensor available.",
                )
            self._check_sensor_required_fields(result, sensor_config_path, sensor)
            if sensor.observation_key not in plan.sensor_config.observation_schema:
                result.add(
                    "observation_schema_missing",
                    f"{sensor_config_path} observation_schema.{sensor.observation_key}",
                    "dtype and shape for the required observation channel",
                    "Add the observation_schema entry matching the sensor observation_key.",
                )

        if plan.perception_config is not None:
            pipeline_plugin_ids = set(plan.selected_plugins)
            for plugin in plan.plugins:
                if plugin.module and importlib.util.find_spec(plugin.module) is None:
                    result.add(
                        "plugin_module_missing",
                        f"{perception_config_path} plugin_candidates[{plugin.id}].module",
                        f"importable Python module {plugin.module}",
                        "Install the plugin module or update plugin_candidates[].module.",
                    )
                for sensor_id in plugin.requires_sensors:
                    if sensor_id not in sensors:
                        result.add(
                            "plugin_required_sensor_missing",
                            f"{perception_config_path} plugin_candidates[{plugin.id}].requires_sensors",
                            f"sensor {sensor_id} declared in sensor_config_ref",
                            "Add the sensor config or update plugin requires_sensors.",
                        )
                for dep in plugin.requires_plugins:
                    if dep not in pipeline_plugin_ids:
                        result.add(
                            "plugin_dependency_missing",
                            f"{perception_config_path} plugin_candidates[{plugin.id}].requires_plugins",
                            f"pipeline includes dependency plugin {dep}",
                            "Add the dependency to pipelines[].use_plugins before this plugin.",
                        )
            for model in plan.models:
                self._check_model(result, perception_config_path, model)

        if not result.ok:
            raise PerceptionPreflightError(result.summary())

    def _check_sensor_required_fields(self, result, path: Path, sensor) -> None:
        for field in sensor.required_fields:
            value = sensor.model_dump()
            present = True
            for part in field.split("."):
                if isinstance(value, dict) and value.get(part) not in (None, ""):
                    value = value[part]
                else:
                    present = False
                    break
            if not present:
                result.add(
                    "sensor_required_field_missing",
                    f"{path} sensors[{sensor.id}].{field}",
                    "configured value",
                    f"Add {field} under sensor {sensor.id}.",
                )
                continue
            if field in {"calibration.intrinsics", "calibration.extrinsics"}:
                cal_path = self.resolver.resolve_path(str(value))
                if not cal_path.exists():
                    result.add(
                        "calibration_file_missing",
                        f"{path} sensors[{sensor.id}].{field}",
                        f"readable file at {value}",
                        "Create the calibration file or update the calibration path.",
                    )

    def _check_model(
        self,
        result: PreflightResult,
        perception_config_path: Path | None,
        model: PerceptionModelSpec,
    ) -> None:
        field_prefix = f"{perception_config_path} models[{model.id}]"
        for package in model.required_packages:
            if importlib.util.find_spec(package) is None:
                result.add(
                    "required_package_missing",
                    f"{field_prefix}.required_packages",
                    f"importable Python package {package}",
                    model.install_hint or f"Install Python package {package}.",
                )
        if model.provider == "python_module":
            if not model.module or importlib.util.find_spec(model.module) is None:
                result.add(
                    "python_module_missing",
                    f"{field_prefix}.module",
                    "importable Python module",
                    model.install_hint or "Install the module or update models[].module.",
                )
        elif model.provider == "local_checkpoint":
            if not model.checkpoint_path:
                result.add(
                    "checkpoint_path_missing",
                    f"{field_prefix}.checkpoint_path",
                    "readable checkpoint path",
                    "Set checkpoint_path for this model.",
                )
            else:
                checkpoint = self.resolver.resolve_path(model.checkpoint_path)
                if not checkpoint.exists():
                    result.add(
                        "checkpoint_file_missing",
                        f"{field_prefix}.checkpoint_path",
                        f"readable checkpoint at {model.checkpoint_path}",
                        model.install_hint or "Download the checkpoint or update checkpoint_path.",
                    )
        elif model.provider in {"local_worker", "remote_endpoint"}:
            url = model.healthcheck or model.endpoint
            if not url:
                result.add(
                    "model_healthcheck_missing",
                    f"{field_prefix}.healthcheck",
                    "healthcheck or endpoint URL",
                    "Set healthcheck for this worker/endpoint model.",
                )
                return
            try:
                response = httpx.get(url, timeout=1.0)
                if response.status_code >= 400:
                    raise httpx.HTTPError(f"HTTP {response.status_code}")
            except Exception:
                result.add(
                    "model_endpoint_unreachable",
                    f"{field_prefix}.healthcheck",
                    f"{url} reachable",
                    model.install_hint or "Start the model worker or update the endpoint.",
                )
