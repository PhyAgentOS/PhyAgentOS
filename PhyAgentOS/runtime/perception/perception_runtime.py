"""High-level target-configured perception runtime."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from uuid import uuid4

from PhyAgentOS.runtime.errors import SchemaValidationError
from PhyAgentOS.runtime.perception.config_resolver import (
    PerceptionConfigResolver,
    ResolvedPerceptionPlan,
)
from PhyAgentOS.runtime.perception.environment_writer import EnvironmentWriter
from PhyAgentOS.runtime.perception.plugin_pipeline import PerceptionPluginPipeline
from PhyAgentOS.runtime.perception.preflight import PerceptionPreflightChecker
from PhyAgentOS.runtime.perception.sensor_frame_builder import SensorFrameBuilder
from PhyAgentOS.runtime.watchdog.scheduler import ScheduledSession


class PerceptionRuntime:
    def __init__(self, runtime_workspace: Path, environment_workspace: Path | None = None):
        self.workspace = runtime_workspace
        self.environment_workspace = environment_workspace or runtime_workspace
        self.resolver = PerceptionConfigResolver(runtime_workspace)
        self.preflight = PerceptionPreflightChecker(runtime_workspace, self.resolver)
        self.frame_builder = SensorFrameBuilder()
        self.pipeline = PerceptionPluginPipeline()
        self.writer = EnvironmentWriter(self.environment_workspace)

    def resolve_and_check(self, scheduled: ScheduledSession) -> ResolvedPerceptionPlan | None:
        plan = self.resolver.resolve(scheduled)
        if plan is None:
            return None
        self.preflight.check(plan)
        return plan

    def refresh_environment(self, plan: ResolvedPerceptionPlan, target, observation=None) -> None:
        if not plan.requested_outputs:
            return
        started = perf_counter()
        run_id = f"perc_{uuid4().hex[:12]}"
        if observation is None:
            observation_getter = getattr(target, "observe_for_environment", None)
            if callable(observation_getter):
                observation = observation_getter({"session_id": plan.session_id, "environment_refresh": True})
            else:
                observation = target.observe()
        frame = self.frame_builder.build(plan, observation)
        delta = self.pipeline.run(plan, frame)
        self._check_generated_outputs(plan, delta.generated_outputs)
        latency_ms = (perf_counter() - started) * 1000.0
        artifact_dir = str(Path(plan.artifact_dir) / plan.session_id)
        for obj in delta.objects.values():
            obj.source.perception_run_id = run_id
            obj.source.pipeline = list(plan.selected_plugins)
        self.writer.write(
            target_id=plan.target_id,
            session_id=plan.session_id,
            run_id=run_id,
            sensor_config_ref=plan.sensor_config_ref,
            perception_config_ref=plan.perception_config_ref,
            pipeline_id=plan.selected_pipeline_id,
            pipeline=plan.selected_plugins,
            requested_outputs=plan.requested_outputs,
            artifact_dir=artifact_dir,
            delta=delta,
            latency_ms=latency_ms,
        )

    def _check_generated_outputs(self, plan: ResolvedPerceptionPlan, generated_outputs: list[str]) -> None:
        missing = sorted(set(plan.requested_outputs) - set(generated_outputs))
        if missing:
            raise SchemaValidationError(
                "perception pipeline "
                f"{plan.selected_pipeline_id or '<none>'} did not generate required outputs: "
                f"{', '.join(missing)}"
            )
