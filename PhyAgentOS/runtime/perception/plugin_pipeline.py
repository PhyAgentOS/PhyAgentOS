"""Perception plugin pipeline execution."""

from __future__ import annotations

import importlib
from typing import Any

from PhyAgentOS.plugins.perception_plugins.base import BasePerceptionPlugin
from PhyAgentOS.plugins.perception_plugins.dummy_segmenter import DummySegmenter
from PhyAgentOS.plugins.perception_plugins.rgbd_object_builder import RGBDObjectBuilder
from PhyAgentOS.plugins.perception_plugins.sim_oracle import SimOraclePlugin
from PhyAgentOS.runtime.errors import SchemaValidationError
from PhyAgentOS.runtime.perception.config_resolver import ResolvedPerceptionPlan
from PhyAgentOS.runtime.perception.sensor_frame import SensorFrame
from PhyAgentOS.runtime.schemas.perception import EnvironmentDelta

_BUILTIN_PLUGINS: dict[str, type[BasePerceptionPlugin]] = {
    "dummy_segmenter": DummySegmenter,
    "dummy_2d_segmenter": DummySegmenter,
    "rgbd_object_builder": RGBDObjectBuilder,
    "sim_oracle": SimOraclePlugin,
}


class PerceptionPluginPipeline:
    def run(self, plan: ResolvedPerceptionPlan, frame: SensorFrame) -> EnvironmentDelta:
        context: dict[str, Any] = {}
        merged = EnvironmentDelta()
        for candidate in plan.plugins:
            plugin = self._build_plugin(candidate.id, candidate.module, candidate.class_name, candidate.config)
            delta = plugin.run(frame, context)
            context[candidate.id] = delta
            for key, obj in delta.objects.items():
                merged.objects[key] = obj
            merged.relations.extend(delta.relations)
            for output in delta.generated_outputs:
                if output not in merged.generated_outputs:
                    merged.generated_outputs.append(output)
            for scope in delta.refresh_scope:
                if scope not in merged.refresh_scope:
                    merged.refresh_scope.append(scope)
        return merged

    def _build_plugin(
        self,
        plugin_id: str,
        module_name: str | None,
        class_name: str | None,
        config: dict[str, Any],
    ) -> BasePerceptionPlugin:
        plugin_cls = _BUILTIN_PLUGINS.get(plugin_id)
        if plugin_cls is None and module_name:
            module = importlib.import_module(module_name)
            if class_name:
                plugin_cls = getattr(module, class_name)
            else:
                plugin_cls = getattr(module, "Plugin", None)
        if plugin_cls is None:
            raise SchemaValidationError(
                f"perception plugin {plugin_id} is not built in and has no importable module/class"
            )
        return plugin_cls(plugin_id=plugin_id, config=config)

