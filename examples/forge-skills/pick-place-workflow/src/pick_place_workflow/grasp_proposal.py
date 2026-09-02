"""Compatibility exports for the PAOS-owned grasp-proposal runtime.

The public implementation lives under ``PhyAgentOS.forge.capability_runtime``;
this module preserves the existing Skill import names without owning generic
contract or validation semantics.
"""

from PhyAgentOS.forge.capability_runtime.grasp_proposal import (
    GRASP_ENDPOINT_ID,
    GRASP_OPERATION,
    GRASP_TOOL_ID,
    GRASP_TOOL_SPEC,
    GraspProposalEndpoint,
    GraspProposalProvider,
    GraspProposalSnapshot,
    _validate_candidate,
    validate_arguments,
    validate_snapshot,
)

__all__ = [
    "GRASP_ENDPOINT_ID",
    "GRASP_OPERATION",
    "GRASP_TOOL_ID",
    "GRASP_TOOL_SPEC",
    "GraspProposalEndpoint",
    "GraspProposalProvider",
    "GraspProposalSnapshot",
    "validate_arguments",
    "validate_snapshot",
    "_validate_candidate",
]
