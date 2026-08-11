"""SAM3 open-vocabulary plugin placeholder with lazy dependency loading."""

from __future__ import annotations

from PhyAgentOS.plugins.perception_plugins.base import BasePerceptionPlugin
from PhyAgentOS.runtime.errors import SchemaValidationError
from PhyAgentOS.runtime.perception.sensor_frame import SensorFrame
from PhyAgentOS.runtime.schemas.perception import EnvironmentDelta


class SAM3OpenVocabPlugin(BasePerceptionPlugin):
    def preflight(self) -> None:
        raise SchemaValidationError("SAM3 plugin requires an external worker in this MVP")

    def run(self, frame: SensorFrame, context: dict) -> EnvironmentDelta:
        raise SchemaValidationError("SAM3 plugin is not available in dependency-free MVP")

