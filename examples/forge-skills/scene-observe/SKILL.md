---
name: scene-observe
description: Read a fresh, calibrated scene observation without causing a physical effect.
metadata: {"PhyAgentOS":{"always":false,"requires":{"runtime":["scene-observe"]}}}
---

# Scene Observe

Use `scene.observe` only to obtain measured observation artifacts. Before invocation,
read the ToolSpec and live context through `forge_tool_context`; use only the declared
sensor reference, frame, and freshness fields. A successful Query does not authorize
planning or motion and must not be passed directly to an Action.

The Query returns an explicit status, capture timestamp, scene revision, frame identity,
calibration reference, freshness measurement, and opaque artifact references. Treat
`unavailable`, `stale`, and `invalid` as blockers. Do not retry a stale or missing-
calibration result by weakening `max_age_ms`; obtain a new observation or operator input.

Use `scene.understand` only after a successful `scene.observe` result. Pass the returned
`observation_ref`, scene revision, frame, calibration reference, freshness, and artifact
references unchanged. The understanding Query returns entity/relation claims and spatial
envelopes with confidence and provenance; it does not authorize grasping, planning, or
motion. Reject stale, unavailable, ambiguous, or invalid results before any future Action.
