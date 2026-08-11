"""Resolve target/skill perception configuration into an executable plan."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from PhyAgentOS.runtime.errors import SchemaValidationError
from PhyAgentOS.runtime.schemas.perception import (
    PerceptionConfigDocument,
    PerceptionModelSpec,
    PerceptionPipelineSpec,
    PerceptionPluginCandidate,
)
from PhyAgentOS.runtime.schemas.sensor_config import SensorConfigDocument, SensorSpec
from PhyAgentOS.runtime.watchdog.scheduler import ScheduledSession


class ResolvedPerceptionPlan(BaseModel):
    target_id: str
    skillruntime_id: str
    session_id: str
    sensor_config_ref: str
    perception_config_ref: str | None = None
    required_sensors: list[str] = Field(default_factory=list)
    requested_outputs: list[str] = Field(default_factory=list)
    selected_pipeline_id: str | None = None
    selected_plugins: list[str] = Field(default_factory=list)
    required_models: list[str] = Field(default_factory=list)
    artifact_dir: str

    sensor_config: SensorConfigDocument
    perception_config: PerceptionConfigDocument | None = None
    pipeline: PerceptionPipelineSpec | None = None
    plugins: list[PerceptionPluginCandidate] = Field(default_factory=list)
    models: list[PerceptionModelSpec] = Field(default_factory=list)


class PerceptionConfigResolver:
    def __init__(self, workspace: Path):
        self.workspace = workspace

    def resolve(self, scheduled: ScheduledSession) -> ResolvedPerceptionPlan | None:
        required_sensors = list(scheduled.skillruntime_spec.requires.sensors)
        requested_outputs = list(scheduled.skillruntime_spec.requires.environment_outputs)
        if not required_sensors and not requested_outputs:
            return None

        target = scheduled.target_spec
        perception_refs = target.perception
        if not perception_refs.enabled:
            raise SchemaValidationError(
                f"target {target.id} perception.enabled must be true for skill {scheduled.skillruntime_id}"
            )
        if perception_refs.strict_preflight is not True:
            raise SchemaValidationError(
                f"target {target.id} perception.strict_preflight must be true"
            )
        if perception_refs.sensor_config_ref is None:
            raise SchemaValidationError(
                f"TARGETS.md targets[{target.id}].perception.sensor_config_ref is required"
            )

        sensor_path = self.resolve_path(perception_refs.sensor_config_ref)
        sensor_config = self._load_sensor_config(sensor_path)
        if sensor_config.target_id != target.id:
            raise SchemaValidationError(
                f"{sensor_path} target_id {sensor_config.target_id!r} does not match target {target.id!r}"
            )

        perception_config = None
        perception_path: Path | None = None
        pipeline = None
        plugins: list[PerceptionPluginCandidate] = []
        models: list[PerceptionModelSpec] = []
        selected_plugins: list[str] = []
        required_models: list[str] = []

        if requested_outputs:
            if perception_refs.perception_config_ref is None:
                raise SchemaValidationError(
                    f"TARGETS.md targets[{target.id}].perception.perception_config_ref is required"
                )
            perception_path = self.resolve_path(perception_refs.perception_config_ref)
            perception_config = self._load_perception_config(perception_path)
            if perception_config.strict_preflight is not True:
                raise SchemaValidationError(
                    f"{perception_path} strict_preflight must be true"
                )
            if perception_config.target_id != target.id:
                raise SchemaValidationError(
                    f"{perception_path} target_id {perception_config.target_id!r} does not match target {target.id!r}"
                )
            pipeline = self._select_pipeline(perception_config, requested_outputs, perception_path)
            plugin_by_id = {plugin.id: plugin for plugin in perception_config.plugin_candidates}
            model_by_id = {model.id: model for model in perception_config.models}
            for plugin_id in pipeline.use_plugins:
                plugin = plugin_by_id.get(plugin_id)
                if plugin is None:
                    raise SchemaValidationError(
                        f"{perception_path} pipelines[{pipeline.id}].use_plugins references unknown plugin {plugin_id}"
                    )
                plugins.append(plugin)
                selected_plugins.append(plugin.id)
                required_sensors = _append_unique(required_sensors, plugin.requires_sensors)
                if plugin.model_ref:
                    model = model_by_id.get(plugin.model_ref)
                    if model is None:
                        raise SchemaValidationError(
                            f"{perception_path} plugin_candidates[{plugin.id}].model_ref references unknown model {plugin.model_ref}"
                        )
                    if model.id not in required_models:
                        required_models.append(model.id)
                        models.append(model)

        artifact_dir = perception_refs.artifact_dir or Path("artifacts") / "perception" / target.id
        return ResolvedPerceptionPlan(
            target_id=target.id,
            skillruntime_id=scheduled.skillruntime_id,
            session_id=scheduled.session.session_id,
            sensor_config_ref=str(perception_refs.sensor_config_ref),
            perception_config_ref=str(perception_refs.perception_config_ref)
            if perception_refs.perception_config_ref
            else None,
            required_sensors=required_sensors,
            requested_outputs=requested_outputs,
            selected_pipeline_id=pipeline.id if pipeline else None,
            selected_plugins=selected_plugins,
            required_models=required_models,
            artifact_dir=str(artifact_dir),
            sensor_config=sensor_config,
            perception_config=perception_config,
            pipeline=pipeline,
            plugins=plugins,
            models=models,
        )

    def resolve_path(self, path: str | Path) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return self.workspace / candidate

    def _load_sensor_config(self, path: Path) -> SensorConfigDocument:
        data = self._load_yaml(path)
        try:
            return SensorConfigDocument.model_validate(data)
        except ValidationError as exc:
            raise SchemaValidationError(f"invalid sensor config {path}: {exc}") from exc

    def _load_perception_config(self, path: Path) -> PerceptionConfigDocument:
        data = self._load_yaml(path)
        try:
            return PerceptionConfigDocument.model_validate(data)
        except ValidationError as exc:
            raise SchemaValidationError(f"invalid perception config {path}: {exc}") from exc

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise SchemaValidationError(f"configuration file not found: {path}")
        if not path.is_file():
            raise SchemaValidationError(f"configuration path is not a file: {path}")
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except OSError as exc:
            raise SchemaValidationError(f"configuration file is not readable: {path}") from exc
        except yaml.YAMLError as exc:
            raise SchemaValidationError(f"configuration file is invalid YAML: {path}") from exc
        if not isinstance(payload, dict):
            raise SchemaValidationError(f"configuration file must contain a YAML mapping: {path}")
        return payload

    def _select_pipeline(
        self,
        config: PerceptionConfigDocument,
        requested_outputs: list[str],
        path: Path,
    ) -> PerceptionPipelineSpec:
        requested = set(requested_outputs)
        matches = [
            pipeline for pipeline in config.pipelines if requested.issubset(set(pipeline.required_outputs))
        ]
        if not matches:
            raise SchemaValidationError(
                f"{path} has no pipeline that covers required outputs: {', '.join(requested_outputs)}"
            )
        return matches[0]


def sensor_by_id(config: SensorConfigDocument) -> dict[str, SensorSpec]:
    return {sensor.id: sensor for sensor in config.sensors}


def _append_unique(values: list[str], additions: list[str]) -> list[str]:
    seen = set(values)
    for value in additions:
        if value not in seen:
            values.append(value)
            seen.add(value)
    return values
