"""Simulator-neutral Forge capability runtime APIs."""

from .grasp_proposal import GRASP_TOOL_SPEC as GRASP_PROPOSAL_TOOL_SPEC
from .grasp_proposal import (
    GraspProposalEndpoint,
    GraspProposalSnapshot,
)
from .grasp_proposal import (
    normalize_snapshot as normalize_grasp_snapshot,
)
from .http_transport import CapabilityRuntimeTransport
from .manipulation_capabilities import (
    CAPABILITY_ENDPOINT_ID,
    CAPABILITY_OPERATION,
    CAPABILITY_TOOL_ID,
    CAPABILITY_TOOL_SPEC,
    CapabilitySnapshotEndpoint,
    CapabilitySnapshotProvider,
)
from .manipulation_prepare import (
    MANIPULATION_TOOL_SPEC,
    ManipulationPreparationEndpoint,
    PreparationSnapshot,
)
from .observation import (
    OBSERVATION_TOOL_SPEC,
    ObservationContractError,
    ObservationEndpoint,
)
from .ports import (
    ActionAdmission,
    ActionEndpoint,
    EnvironmentAdapter,
    GraspProposalProvider,
    ManipulationExecutor,
    ObservationSource,
    QueryEndpoint,
    ReadinessEvaluator,
    SceneUnderstandingProvider,
)
from .runtime import (
    CapabilityRuntime,
    CapabilityRuntimeError,
    DuplicateToolError,
    EndpointRegistration,
    Invocation,
    ToolContractError,
    UnknownToolError,
)
from .understanding import TOOL_SPEC as SCENE_UNDERSTANDING_TOOL_SPEC
from .understanding import (
    SceneUnderstandingEndpoint,
    UnderstandingSnapshot,
)

__all__ = [
    "ActionAdmission",
    "ActionEndpoint",
    "CapabilityRuntime",
    "CapabilityRuntimeTransport",
    "CapabilityRuntimeError",
    "DuplicateToolError",
    "EndpointRegistration",
    "EnvironmentAdapter",
    "GraspProposalProvider",
    "GraspProposalEndpoint",
    "GraspProposalSnapshot",
    "normalize_grasp_snapshot",
    "GRASP_PROPOSAL_TOOL_SPEC",
    "MANIPULATION_TOOL_SPEC",
    "CAPABILITY_ENDPOINT_ID",
    "CAPABILITY_OPERATION",
    "CAPABILITY_TOOL_ID",
    "CAPABILITY_TOOL_SPEC",
    "CapabilitySnapshotEndpoint",
    "CapabilitySnapshotProvider",
    "ManipulationPreparationEndpoint",
    "ObservationContractError",
    "ObservationEndpoint",
    "OBSERVATION_TOOL_SPEC",
    "PreparationSnapshot",
    "Invocation",
    "ManipulationExecutor",
    "ObservationSource",
    "QueryEndpoint",
    "ReadinessEvaluator",
    "SceneUnderstandingProvider",
    "SceneUnderstandingEndpoint",
    "SCENE_UNDERSTANDING_TOOL_SPEC",
    "UnderstandingSnapshot",
    "ToolContractError",
    "UnknownToolError",
]
