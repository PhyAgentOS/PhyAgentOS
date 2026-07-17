# Runtime Sessions

```yaml
version: runtime_sessions_v1
sessions:
- session_id: sess_scout_forward
  replan_attempt: 0
  goal_id: goal_scout_forward
  target_ref: target://scout2_real_builtin
  skillruntime_ref: skillruntime://scout2_builtin_command
  task_description: move forward
  verification_profile: strict
  status: succeeded
  priority: normal
  updated_at: '2026-07-17T03:15:34.210572Z'
  claimed_by: runtime-watchdog@szh-Legion-Y7000P-2019-PG0
  claim_token: 68a59bf2a63442e593ea688dd72b8422
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 5.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    adapter_resolution: strict_auto
  execution:
    max_steps: 4
    replan_every: 8
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - text: 前进
    reset_policy: session_runner
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default
    stop_on_policy_timeout: true
  result:
    status: succeeded
    success: true
    num_steps: 0
    artifact_dir: artifacts/runtime/sess_scout_forward
    metadata:
      message: forward
      return_value: 1.0
      num_steps: 1
      final_status: {}
      artifacts: {}
- session_id: sess_scout_turn
  replan_attempt: 0
  goal_id: goal_scout_turn
  target_ref: target://scout2_real_builtin
  skillruntime_ref: skillruntime://scout2_builtin_command
  task_description: turn left
  verification_profile: strict
  status: succeeded
  priority: normal
  updated_at: '2026-07-17T03:16:49.170158Z'
  claimed_by: runtime-watchdog@szh-Legion-Y7000P-2019-PG0
  claim_token: 57c13dae2e2942db99e44dccbf662223
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 5.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    adapter_resolution: strict_auto
  execution:
    max_steps: 4
    replan_every: 8
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - text: 左转
    reset_policy: session_runner
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default
    stop_on_policy_timeout: true
  result:
    status: succeeded
    success: true
    num_steps: 0
    artifact_dir: artifacts/runtime/sess_scout_turn
    metadata:
      message: turn_left
      return_value: 1.0
      num_steps: 1
      final_status: {}
      artifacts: {}
- session_id: sess_scout_stop
  replan_attempt: 0
  goal_id: goal_scout_stop
  target_ref: target://scout2_real_builtin
  skillruntime_ref: skillruntime://scout2_builtin_command
  task_description: stop
  verification_profile: strict
  status: succeeded
  priority: normal
  updated_at: '2026-07-17T03:32:15.896197Z'
  claimed_by: runtime-watchdog@szh-Legion-Y7000P-2019-PG0
  claim_token: 72bdbb2911f44aa5b2bdec0644499dc4
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 5.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    adapter_resolution: strict_auto
  execution:
    max_steps: 1
    replan_every: 8
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - command: stop
    reset_policy: session_runner
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default
    stop_on_policy_timeout: true
  result:
    status: succeeded
    success: true
    num_steps: 0
    artifact_dir: artifacts/runtime/sess_scout_stop
    metadata:
      message: stop
      return_value: 1.0
      num_steps: 1
      final_status: {}
      artifacts: {}
- session_id: sess_scout_forward_0_1m
  replan_attempt: 0
  goal_id: goal_scout_forward_0_1m
  target_ref: target://scout2_real_builtin
  skillruntime_ref: skillruntime://scout2_builtin_command
  task_description: move forward 0.1m
  verification_profile: strict
  status: succeeded
  priority: normal
  updated_at: '2026-07-17T03:34:22.576836Z'
  claimed_by: runtime-watchdog@szh-Legion-Y7000P-2019-PG0
  claim_token: 27f4e22b1d0040549f24ee5abfe73dca
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 5.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    adapter_resolution: strict_auto
  execution:
    max_steps: 4
    replan_every: 8
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - command: forward
      params:
        distance_m: 0.1
    reset_policy: session_runner
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default
    stop_on_policy_timeout: true
  result:
    status: succeeded
    success: true
    num_steps: 0
    artifact_dir: artifacts/runtime/sess_scout_forward_0_1m
    metadata:
      message: forward
      return_value: 1.0
      num_steps: 1
      final_status: {}
      artifacts: {}
- session_id: sess_scout_forward_0_1m_2
  replan_attempt: 0
  goal_id: goal_scout_forward_0_1m_2
  target_ref: target://scout2_real_builtin
  skillruntime_ref: skillruntime://scout2_builtin_command
  task_description: move forward 0.1m
  verification_profile: strict
  status: succeeded
  priority: normal
  updated_at: '2026-07-17T06:06:00.172900Z'
  claimed_by: runtime-watchdog@szh-Legion-Y7000P-2019-PG0
  claim_token: 58d1a23157d84891ba54bcd777bf2113
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 5.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    adapter_resolution: strict_auto
  execution:
    max_steps: 4
    replan_every: 8
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - command: forward
      params:
        distance_m: 0.1
    reset_policy: session_runner
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default
    stop_on_policy_timeout: true
  result:
    status: succeeded
    success: true
    num_steps: 0
    artifact_dir: artifacts/runtime/sess_scout_forward_0_1m_2
    metadata:
      message: forward
      return_value: 1.0
      num_steps: 1
      final_status: {}
      artifacts: {}
- session_id: sess_scout_forward_0_1m_3
  replan_attempt: 0
  goal_id: goal_scout_forward_0_1m_3
  target_ref: target://scout2_real_builtin
  skillruntime_ref: skillruntime://scout2_builtin_command
  task_description: move forward 0.1m
  verification_profile: strict
  status: succeeded
  priority: normal
  updated_at: '2026-07-17T06:06:40.292633Z'
  claimed_by: runtime-watchdog@szh-Legion-Y7000P-2019-PG0
  claim_token: 0b372a8e0a80411785d8a69f42462b34
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 5.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    adapter_resolution: strict_auto
  execution:
    max_steps: 4
    replan_every: 8
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - command: forward
      params:
        distance_m: 0.1
    reset_policy: session_runner
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default
    stop_on_policy_timeout: true
  result:
    status: succeeded
    success: true
    num_steps: 0
    artifact_dir: artifacts/runtime/sess_scout_forward_0_1m_3
    metadata:
      message: forward
      return_value: 1.0
      num_steps: 1
      final_status: {}
      artifacts: {}
- session_id: sess_scout_backward_0_1m_2
  replan_attempt: 0
  goal_id: goal_scout_backward_0_1m_2
  target_ref: target://scout2_real_builtin
  skillruntime_ref: skillruntime://scout2_builtin_command
  task_description: move backward 0.1m
  verification_profile: strict
  status: succeeded
  priority: normal
  updated_at: '2026-07-17T06:20:20.242989Z'
  claimed_by: runtime-watchdog@szh-Legion-Y7000P-2019-PG0
  claim_token: 605a283221194af18cbe13cc62c467d5
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 5.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    adapter_resolution: strict_auto
  execution:
    max_steps: 4
    replan_every: 8
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - command: backward
      params:
        distance_m: 0.1
    reset_policy: session_runner
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default
    stop_on_policy_timeout: true
  result:
    status: succeeded
    success: true
    num_steps: 0
    artifact_dir: artifacts/runtime/sess_scout_backward_0_1m_2
    metadata:
      message: backward
      return_value: 1.0
      num_steps: 1
      final_status: {}
      artifacts: {}
- session_id: sess_scout_turn_right_15_fwd_0_1m_turn_right_15_2
  replan_attempt: 0
  goal_id: goal_scout_turn_right_15_fwd_0_1m_turn_right_15_2
  target_ref: target://scout2_real_builtin
  skillruntime_ref: skillruntime://scout2_builtin_command
  task_description: turn right 15°, move forward 0.1m, turn right 15°
  verification_profile: strict
  status: succeeded
  priority: normal
  updated_at: '2026-07-17T06:23:18.598994Z'
  claimed_by: runtime-watchdog@szh-Legion-Y7000P-2019-PG0
  claim_token: 17382b0385d14a1b8cb8bb5a3c434007
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 5.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    adapter_resolution: strict_auto
  execution:
    max_steps: 6
    replan_every: 8
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - command: turn_right
      params:
        angle_deg: 15
    - command: forward
      params:
        distance_m: 0.1
    - command: turn_right
      params:
        angle_deg: 15
    reset_policy: session_runner
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default
    stop_on_policy_timeout: true
  result:
    status: succeeded
    success: true
    num_steps: 0
    artifact_dir: artifacts/runtime/sess_scout_turn_right_15_fwd_0_1m_turn_right_15_2
    metadata:
      message: turn_right
      return_value: 3.0
      num_steps: 3
      final_status: {}
      artifacts: {}
```
