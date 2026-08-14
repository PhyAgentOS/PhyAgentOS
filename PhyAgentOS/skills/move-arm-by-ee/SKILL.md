---
name: move-arm-by-ee
description: Resolve a relative end-effector motion and execute the resulting absolute pose.
metadata: {"PhyAgentOS":{"always":false,"requires":{"runtime":["move-arm-by-ee"]}}}
---

# Move Arm by End-Effector

Use this skill to translate a user's relative end-effector request into a safe
Query-to-Action sequence. Use only the stable Tool IDs `motion.resolve_relative_pose`
and `motion.move_pose`. Discover their live schemas and robot frame profile before
calling them; never invent unavailable groups, frames, limits, or defaults.

Use the PAOS bridge tools `forge_tool_context`, `forge_tool_query`,
`forge_tool_start_action`, `forge_tool_action_status`, `forge_tool_action_result`, and
`forge_tool_cancel_action`. The bridge tool names are transport operations; always pass
the stable Forge Tool ID explicitly. Do not use shell commands or construct Gateway HTTP
requests directly.

This Skill owns task-level Tool selection, sequencing, retry, and replanning only. It
must not perform FK, IK, joint-trajectory generation, controller execution, settling,
or final motion residual validation. Relative-pose math belongs to the Query provider;
IK, motion planning, physical execution orchestration, and residual validation belong
to the Motion Action provider.

## 1. Interpret the request

Resolve ambiguity before moving. Confirm the arm/group, distance, direction, translation
frame, orientation change, speed, and tolerances whenever they are not explicit or cannot
be derived from the live capability context.

Build the `motion.resolve_relative_pose` arguments as follows:

- `group_name`: the configured arm group selected by the user or capability context.
- `target_frame`: the configured end-effector/tool-center-point frame.
- `reference`: always `current`.
- `translation_frame`: `tcp` for directions relative to the current end effector; `base`
  for directions expressed in the configured robot base frame. Do not guess what words
  such as "up", "forward", or "left" mean without the frame profile.
- `translation_m`: finite SI-metre offsets with exactly `x`, `y`, and `z`. Convert units
  explicitly; unspecified axes are zero.
- `orientation_mode`: `preserve` when orientation must not change; `apply_delta` for a
  requested local end-effector rotation.
- `axis_angle_rad`: `null` with `preserve`; otherwise a rotation vector whose direction
  is the local rotation axis and whose magnitude is radians. Convert degrees to radians.
- `max_state_age_ms`: a positive freshness bound appropriate to the configured safety
  policy. Do not silently relax it to make a stale query pass.

For `apply_delta`, the orientation delta is local to the current end-effector frame.
Do not reinterpret it as a base-frame rotation.

Example for "move the tool 3 cm along its positive Z axis without rotating":

```json
{
  "group_name": "piper_arm",
  "target_frame": "tcp",
  "reference": "current",
  "translation_frame": "tcp",
  "translation_m": {"x": 0.0, "y": 0.0, "z": 0.03},
  "orientation_mode": "preserve",
  "axis_angle_rad": null,
  "max_state_age_ms": 200
}
```

The names and freshness value above are illustrative. Replace them with values allowed
by the live capability context.

## 2. Resolve, then move

1. Establish a stationary window before invoking `motion.resolve_relative_pose`.
2. Invoke the Query and require a succeeded result containing an absolute `target_pose`,
   frame information, state age, and source snapshot.
3. Reject a result whose state age exceeds the requested bound, whose frames do not match
   the intended group/tool, or whose snapshot is missing or inconsistent.
4. Keep the robot stationary from the source snapshot through `motion.move_pose`
   admission. Query and Action are not atomic.
5. If orchestration can observe snapshot versions, reject an unexpectedly changed source
   snapshot and resolve again. Never reuse a target pose after motion, reset, tool change,
   or loss of state freshness.
6. Pass the returned absolute `target_pose` unchanged to `motion.move_pose`, with:
   - the same `group_name` and `target_frame`;
   - `reference_frame` from the resolved frame information;
   - positive `velocity_scale`, `acceleration_scale`, position tolerance, and orientation
     tolerance selected from the user's request and configured limits;
   - an optional positive requested duration only when supported and justified.

Do not calculate a replacement absolute pose from memory, and do not send joint state or
other local runtime data through the Tool request.

## 3. Track execution

- Treat Action acceptance as admission, not completion.
- Retain the returned invocation identity and use the Tool lifecycle status and result
  operations for that same invocation.
- Poll status with bounded intervals and a task deadline. Progress events are advisory.
- Treat the terminal result as authoritative. Report success only for a succeeded result,
  then verify the user's physical goal from available observations.
- On cancel, issue cancel once with a reason. Requested or accepted cancellation does not
  prove that motion stopped; continue status/result lookup until a terminal result is
  observed.
- Treat `failed`, `cancelled`, `stopped`, and `unknown` as distinct outcomes. An `unknown`
  result means the effect may have occurred and must not be retried blindly.

## 4. Errors and replanning

- Invalid group, frame, schema, units, or limits: do not invoke the Action; correct the
  request or ask the user to clarify.
- Stale or unavailable robot state: keep the robot stationary, obtain a fresh snapshot,
  and rerun `motion.resolve_relative_pose`.
- Busy: identify or wait for the active motion with a bounded policy; cancel it only when
  authorized. Do not create competing moves.
- Planning or reachability failure: do not repeat the identical Action. Replan with a
  smaller relative displacement, safer speed, adjusted tolerances, or validated
  intermediate waypoint.
- Timeout, transport loss, or `unknown`: reconcile the existing invocation through
  status/result and fresh observation before deciding whether any new motion is safe.
- Execution success but goal-verification failure: capture fresh state, express the
  remaining correction as a new relative request, and start again from the Query. Never
  reuse the prior absolute target.

Stop and request human guidance when frame meaning, collision risk, workspace limits, or
the robot's actual state cannot be established.
