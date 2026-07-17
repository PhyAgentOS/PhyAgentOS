# Runtime Lessons

```yaml
version: runtime_lessons_v1
updated_at: '2026-07-17T06:21:20.468795+00:00'
lessons:
- id: lesson_sess_scout_forward_1
  timestamp: '2026-07-17T03:12:18.477561+00:00'
  session_id: sess_scout_forward
  phase: preflight_checking
  error_code: RUNTIME_PREFLIGHT_FAILED
  target_id: scout2_real_builtin
  skillruntime_id: scout2_builtin_command
  summary: 'ACTION_BRIDGE_MISSING: adapter_plan.target_adapter expected registered
    target adapter, found unsupported target adapter: target_adapter://scout_adapter'
  metadata:
    verdict: rejected
    session_id: sess_scout_forward
    target_id: scout2_real_builtin
    skillruntime_id: scout2_builtin_command
    runner_type: SessionRunner
    skill_runtime_kind: builtin
    execution_mode: builtin_command_loop
    missing_items:
    - code: ACTION_BRIDGE_MISSING
      field: adapter_plan.target_adapter
      expected: registered target adapter
      found: 'unsupported target adapter: target_adapter://scout_adapter'
      triggered_by: sess_scout_forward
      fix: Register the target adapter.
    warnings: []
- id: lesson_sess_scout_forward_2
  timestamp: '2026-07-17T03:13:21.240449+00:00'
  session_id: sess_scout_forward
  phase: running
  error_code: TARGET_BUILD
  target_id: scout2_real_builtin
  skillruntime_id: scout2_builtin_command
  summary: 'TargetBuildError: unsupported remote target runtime: ScoutRemoteTargetProxy'
  metadata:
    exception_type: TargetBuildError
    message: 'unsupported remote target runtime: ScoutRemoteTargetProxy'
    session_status: running
- id: lesson_sess_scout_forward_3
  timestamp: '2026-07-17T03:14:02.137236+00:00'
  session_id: sess_scout_forward
  phase: running
  error_code: TARGET_BUILD
  target_id: scout2_real_builtin
  skillruntime_id: scout2_builtin_command
  summary: 'TargetBuildError: unsupported remote target runtime: ScoutRemoteTargetProxy'
  metadata:
    exception_type: TargetBuildError
    message: 'unsupported remote target runtime: ScoutRemoteTargetProxy'
    session_status: running
- id: lesson_sess_scout_forward_4
  timestamp: '2026-07-17T03:14:19.890285+00:00'
  session_id: sess_scout_forward
  phase: running
  error_code: TARGET_BUILD
  target_id: scout2_real_builtin
  skillruntime_id: scout2_builtin_command
  summary: 'TargetBuildError: unsupported remote target runtime: ScoutRemoteTargetProxy'
  metadata:
    exception_type: TargetBuildError
    message: 'unsupported remote target runtime: ScoutRemoteTargetProxy'
    session_status: running
- id: lesson_sess_scout_backward_0_1m_5
  timestamp: '2026-07-17T06:07:22.812266+00:00'
  session_id: sess_scout_backward_0_1m
  phase: running
  error_code: TARGET_PROTOCOL
  target_id: scout2_real_builtin
  skillruntime_id: scout2_builtin_command
  summary: 'TargetProtocolError: TargetProtocolError: rclpy is required outside --dry-run;
    install ROS2 Humble or check environment'
  metadata:
    exception_type: TargetProtocolError
    message: 'TargetProtocolError: rclpy is required outside --dry-run; install ROS2
      Humble or check environment'
    session_status: running
- id: lesson_sess_scout_backward_0_1m_2_6
  timestamp: '2026-07-17T06:19:00.008549+00:00'
  session_id: sess_scout_backward_0_1m_2
  phase: running
  error_code: TARGET_PROTOCOL
  target_id: scout2_real_builtin
  skillruntime_id: scout2_builtin_command
  summary: 'TargetProtocolError: NameError: name ''Twist'' is not defined'
  metadata:
    exception_type: TargetProtocolError
    message: 'NameError: name ''Twist'' is not defined'
    session_status: running
- id: lesson_sess_scout_turn_right_15_fwd_0_1m_turn_right_15_7
  timestamp: '2026-07-17T06:21:20.468781+00:00'
  session_id: sess_scout_turn_right_15_fwd_0_1m_turn_right_15
  phase: running
  error_code: TARGET_PROTOCOL
  target_id: scout2_real_builtin
  skillruntime_id: scout2_builtin_command
  summary: 'TargetProtocolError: InvalidHandle: cannot use Destroyable because destruction
    was requested'
  metadata:
    exception_type: TargetProtocolError
    message: 'InvalidHandle: cannot use Destroyable because destruction was requested'
    session_status: running
```
