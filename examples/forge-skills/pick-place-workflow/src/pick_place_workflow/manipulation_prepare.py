"""Compatibility exports for the PAOS-owned preparation runtime.

The generic, provider-neutral readiness contract is implemented by PAOS.  This
module preserves the existing Skill import names for bundle compatibility.
"""

from PhyAgentOS.forge.capability_runtime.manipulation_prepare import (
    MANIPULATION_TOOL_SPEC,
    PREPARATION_ENDPOINT_ID,
    PREPARATION_OPERATION,
    PREPARATION_TOOL_ID,
    ManipulationPreparationEndpoint,
    PreparationProvider,
    PreparationSnapshot,
    validate_arguments,
    validate_snapshot,
)

__all__ = [
    "PREPARATION_TOOL_ID",
    "PREPARATION_ENDPOINT_ID",
    "PREPARATION_OPERATION",
    "MANIPULATION_TOOL_SPEC",
    "PreparationProvider",
    "PreparationSnapshot",
    "ManipulationPreparationEndpoint",
    "validate_arguments",
    "validate_snapshot",
]
