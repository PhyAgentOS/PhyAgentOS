"""Compatibility exports for the PAOS-owned scene-understanding runtime.

The public implementation lives under ``PhyAgentOS.forge.capability_runtime``;
this module keeps the existing example Skill imports stable without making the
Skill package the owner of generic capability semantics.
"""

from PhyAgentOS.forge.capability_runtime.understanding import TOOL_SPEC as UNDERSTANDING_TOOL_SPEC
from PhyAgentOS.forge.capability_runtime.understanding import (
    SceneUnderstandingEndpoint,
    SceneUnderstandingProvider,
    UnderstandingSnapshot,
    validate_arguments,
    validate_snapshot,
)

UNDERSTANDING_TOOL_ID = "scene.understand"
UNDERSTANDING_ENDPOINT_ID = "scene_understanding"
UNDERSTANDING_OPERATION = "understand"
UnderstandingProvider = SceneUnderstandingProvider

__all__ = [
    "UNDERSTANDING_ENDPOINT_ID",
    "UNDERSTANDING_OPERATION",
    "UNDERSTANDING_TOOL_ID",
    "UNDERSTANDING_TOOL_SPEC",
    "SceneUnderstandingEndpoint",
    "SceneUnderstandingProvider",
    "UnderstandingProvider",
    "UnderstandingSnapshot",
    "validate_arguments",
    "validate_snapshot",
]
