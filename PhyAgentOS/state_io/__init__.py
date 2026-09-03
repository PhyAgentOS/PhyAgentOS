"""PAOS state-file parsing and side-effect-free adapter utilities."""

from PhyAgentOS.state_io.adapters import (
    SessionPreview,
    TargetShadowReport,
    parse_sessions_preview,
    parse_targets_shadow,
    render_environment_projection,
    render_lessons_projection,
    render_skillruntime_projection,
)
from PhyAgentOS.state_io.protocol import (
    ParsedStateFile,
    ProjectionResult,
    StateFileDriftError,
    StateFileError,
    parse_state_file,
    write_projection,
)

__all__ = [
    "ParsedStateFile",
    "ProjectionResult",
    "SessionPreview",
    "StateFileDriftError",
    "StateFileError",
    "TargetShadowReport",
    "parse_sessions_preview",
    "parse_state_file",
    "parse_targets_shadow",
    "render_environment_projection",
    "render_lessons_projection",
    "render_skillruntime_projection",
    "write_projection",
]
