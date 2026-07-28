# Runtime Lessons

```yaml
version: runtime_lessons_v1
updated_at: '2026-07-28T08:10:12.142313+00:00'
lessons:
- id: lesson_squat2stand_dryrun_001_1
  timestamp: '2026-07-28T07:56:26.786094+00:00'
  session_id: squat2stand_dryrun_001
  phase: running
  error_code: TARGET_BUILD
  target_id: g1_real_builtin
  skillruntime_id: g1_builtin_command
  summary: 'TargetBuildError: unsupported remote target runtime: G1RemoteTargetProxy'
  metadata:
    exception_type: TargetBuildError
    message: 'unsupported remote target runtime: G1RemoteTargetProxy'
    session_status: running
- id: lesson_kiss_sequence_001_2
  timestamp: '2026-07-28T08:10:12.142301+00:00'
  session_id: kiss_sequence_001
  phase: running
  error_code: TARGET_PROTOCOL
  target_id: g1_real_builtin
  skillruntime_id: g1_builtin_command
  summary: 'TargetProtocolError: TargetProtocolError: unsupported G1 command: execute_arm_action'
  metadata:
    exception_type: TargetProtocolError
    message: 'TargetProtocolError: unsupported G1 command: execute_arm_action'
    session_status: running
- id: lesson_kiss_sequence_001_3
  timestamp: '2026-07-28T08:10:38.735621+00:00'
  session_id: kiss_sequence_001
  phase: succeeded
  target_id: g1_real_builtin
  skillruntime_id: g1_builtin_command
  summary: 'Fixed: arm gesture command format and YAML special characters'
  metadata:
    issue_1:
      description: 'YAML parsing failed due to → arrow and -> in task_description'
      root_cause: 'YAML treats -> as a mapping indicator; Unicode arrows also cause issues'
      fix: 'Wrap strings containing -> or special chars in double quotes, or use ASCII-safe text'
    issue_2:
      description: 'Arm gesture command format was wrong'
      root_cause: 'Used command: execute_arm_action with params: {action: left_kiss} instead of direct command name'
      fix: 'Use command: left_kiss directly — G1 arm gestures are commands themselves, not sub-actions of execute_arm_action'
    issue_3:
      description: 'Watchdog not running, sessions stuck in pending'
      root_cause: 'Watchdog process was not started'
      fix: 'Start watchdog: python -m PhyAgentOS.runtime.watchdog --workspace <workspace_path>'
    issue_4:
      description: 'reset_policy indentation was wrong'
      root_cause: 'reset_policy was at 2-space indent (same level as runtime_hints) instead of 4-space (inside execution block)'
      fix: 'Ensure reset_policy is indented under execution: with 4 spaces'
```
