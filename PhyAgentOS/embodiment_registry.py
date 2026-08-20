"""Registry helpers for shared/fleet embodiment topologies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PhyAgentOS.config.schema import Config, EmbodimentInstanceConfig
from PhyAgentOS.utils.helpers import ensure_dir, sync_workspace_templates


@dataclass(frozen=True)
class EmbodimentInstance:
    """Resolved robot instance settings."""

    robot_id: str
    workspace: Path
    enabled: bool = True
    profile_name: str | None = None
    shared_environment: Path | None = None

    @property
    def profile_filename(self) -> str:
        name = self.profile_name or self.robot_id
        return name if name.endswith(".md") else f"{name}.md"

    @property
    def shared_environment_path(self) -> Path | None:
        return self.shared_environment


class EmbodimentRegistry:
    """Resolve embodiment knowledge workspaces independently of robot execution."""

    def __init__(self, config: Config):
        self.config = config
        self.mode = config.embodiments.mode
        self.shared_workspace = config.workspace_path
        self._instances = [self._resolve_instance(item) for item in config.embodiments.instances]

    @property
    def is_fleet(self) -> bool:
        return self.mode == "fleet"

    def instances(self, enabled_only: bool = False) -> list[EmbodimentInstance]:
        if not enabled_only:
            return list(self._instances)
        return [instance for instance in self._instances if instance.enabled]

    def get_instance(self, robot_id: str) -> EmbodimentInstance | None:
        for instance in self._instances:
            if instance.robot_id == robot_id:
                return instance
        return None

    def require_instance(self, robot_id: str) -> EmbodimentInstance:
        instance = self.get_instance(robot_id)
        if instance is None:
            raise KeyError(f"Unknown robot_id {robot_id!r}")
        return instance

    def resolve_agent_workspace(self) -> Path:
        return self.shared_workspace

    def resolve_environment_path(self, robot_id: str | None = None, default_workspace: Path | None = None) -> Path:
        if not self.is_fleet:
            return (default_workspace or self.shared_workspace) / "ENVIRONMENT.md"
        if robot_id:
            instance = self.require_instance(robot_id)
            if instance.shared_environment_path:
                return instance.shared_environment_path
        return self.shared_workspace / "ENVIRONMENT.md"

    def resolve_lessons_path(self, default_workspace: Path | None = None) -> Path:
        if self.is_fleet:
            return self.shared_workspace / "LESSONS.md"
        return (default_workspace or self.shared_workspace) / "LESSONS.md"

    def resolve_embodied_path(self, robot_id: str, default_workspace: Path | None = None) -> Path:
        return (default_workspace or self.shared_workspace) / "EMBODIED.md"

    def sync_layout(self) -> list[str]:
        created: list[str] = []
        if not self.is_fleet:
            sync_workspace_templates(self.shared_workspace)
            return created

        ensure_dir(self.shared_workspace)
        created.extend(sync_workspace_templates(self.shared_workspace))

        for instance in self.instances(enabled_only=True):
            ensure_dir(instance.workspace)
        return created

    @classmethod
    def from_config(cls, config: Config | None) -> EmbodimentRegistry | None:
        if config is None:
            return None
        return cls(config)

    def _resolve_instance(self, item: EmbodimentInstanceConfig) -> EmbodimentInstance:
        shared_env = Path(item.shared_environment).expanduser() if item.shared_environment else None
        return EmbodimentInstance(
            robot_id=item.robot_id,
            workspace=Path(item.workspace).expanduser(),
            enabled=item.enabled,
            profile_name=item.profile_name,
            shared_environment=shared_env,
        )
