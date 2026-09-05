"""Shared semantic verification contracts, engine, and service."""

from PhyAgentOS.verification.contracts import (
    EvidenceArtifact,
    EvidenceBundle,
    EvidenceCaptureWindow,
    EvidenceQuality,
    ExecutionError,
    ExecutionRecord,
    ExecutionTimeline,
    ForgeSessionRecord,
    ForgeSessionStatus,
    ForgeTaskRequest,
    RecoveryRequest,
    TaskVerificationContract,
    VerificationEvidencePolicy,
    VerificationState,
    VerificationVerdict,
)
from PhyAgentOS.verification.engine import VerificationEngine
from PhyAgentOS.verification.outcome_projection import (
    CapabilityOutcomeProjection,
    CapabilityOutcomeProjectionError,
    CapabilityOutcomeProjectionResult,
    PostReleaseEvidenceProjection,
    project_terminal_outcomes,
)

__all__ = [
    "EvidenceArtifact",
    "EvidenceBundle",
    "EvidenceCaptureWindow",
    "EvidenceQuality",
    "ExecutionError",
    "ExecutionRecord",
    "ExecutionTimeline",
    "ForgeSessionRecord",
    "ForgeSessionStatus",
    "ForgeTaskRequest",
    "RecoveryRequest",
    "TaskVerificationContract",
    "VerificationEngine",
    "VerificationEvidencePolicy",
    "VerificationState",
    "VerificationVerdict",
    "CapabilityOutcomeProjection",
    "CapabilityOutcomeProjectionError",
    "CapabilityOutcomeProjectionResult",
    "PostReleaseEvidenceProjection",
    "project_terminal_outcomes",
]
