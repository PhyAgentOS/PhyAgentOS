# Runtime Sessions

```yaml
version: runtime_sessions_v1
sessions:
- session_id: squat2stand_dryrun_001
  replan_attempt: 0
  goal_id: dryrun
  target_ref: g1_real_builtin
  skillruntime_ref: g1_builtin_command
  task_description: Dry-run squat2stand posture command only.
  verification_profile: strict
  status: failed
  priority: normal
  updated_at: '2026-07-28T07:56:26.795267Z'
  claimed_by: runtime-watchdog@szh-MS-7D90
  claim_token: 935a4c9a1cb34f52a7f550bb87d2e09b
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 10.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    target_endpoint: targetws://127.0.0.1:9030
    policy_endpoint: openpi://policy-host:8000
    adapter_resolution: strict_auto
  execution:
    max_steps: 1
    replan_every: 8
    replan_every_steps: 1
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - command: squat2stand
    reset_policy: session_runner
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
    preferred_replan_every_steps: 1
  safety_profile:
    profile: default_simulation
    workspace_bounds: default
    stop_on_policy_timeout: true
  result:
    status: failed
    success: false
    error_code: TARGET_BUILD
    error_message: 'unsupported remote target runtime: G1RemoteTargetProxy'
    metadata: {}
- session_id: squat2stand_dryrun_002
  replan_attempt: 0
  goal_id: dryrun
  target_ref: g1_real_builtin
  skillruntime_ref: g1_builtin_command
  task_description: Dry-run squat2stand posture command only (retry).
  verification_profile: strict
  status: succeeded
  priority: normal
  updated_at: '2026-07-28T08:02:28.202180Z'
  claimed_by: runtime-watchdog@szh-MS-7D90
  claim_token: 64cbe2ad327f42e9ac95a8e99ff1d771
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 10.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    target_endpoint: targetws://127.0.0.1:9030
    policy_endpoint: openpi://policy-host:8000
    adapter_resolution: strict_auto
  execution:
    max_steps: 1
    replan_every: 8
    replan_every_steps: 1
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - command: squat2stand
    reset_policy: session_runner
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
    preferred_replan_every_steps: 1
  safety_profile:
    profile: default_simulation
    workspace_bounds: default
    stop_on_policy_timeout: true
  result:
    status: succeeded
    success: true
    num_steps: 0
    artifact_dir: artifacts/runtime/squat2stand_dryrun_002
    metadata:
      message: squat2stand
      return_value: 1.0
      num_steps: 1
      final_status: {}
      artifacts: {}
- session_id: squat2stand_real_001
  replan_attempt: 0
  goal_id: stand_up
  target_ref: g1_real_builtin
  skillruntime_ref: g1_builtin_command
  task_description: Make G1 stand up from squat position.
  verification_profile: strict
  status: succeeded
  priority: normal
  updated_at: '2026-07-28T08:03:09.131600Z'
  claimed_by: runtime-watchdog@szh-MS-7D90
  claim_token: 204623c31bed43b5b604c7ef5730b26b
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 10.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    target_endpoint: targetws://127.0.0.1:9030
    policy_endpoint: openpi://policy-host:8000
    adapter_resolution: strict_auto
  execution:
    max_steps: 1
    replan_every: 8
    replan_every_steps: 1
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - command: squat2stand
    reset_policy: session_runner
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
    preferred_replan_every_steps: 1
  safety_profile:
    profile: default_simulation
    workspace_bounds: default
    stop_on_policy_timeout: true
  result:
    status: succeeded
    success: true
    num_steps: 0
    artifact_dir: artifacts/runtime/squat2stand_real_001
    metadata:
      message: squat2stand
      return_value: 1.0
      num_steps: 1
      final_status: {}
      artifacts: {}
- session_id: kiss_sequence_001
  replan_attempt: 0
  goal_id: kiss_sequence
  target_ref: g1_real_builtin
  skillruntime_ref: g1_builtin_command
  task_description: 'Execute kiss sequence: left_kiss -> right_kiss -> two_hand_kiss.'
  verification_profile: strict
  status: succeeded
  priority: normal
  updated_at: '2026-07-28T08:10:38.735621Z'
  claimed_by: runtime-watchdog@szh-MS-7D90
  claim_token: bb28acda959b4b63b8039431757bda1d
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 10.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    target_endpoint: targetws://127.0.0.1:9030
    policy_endpoint: openpi://policy-host:8000
    adapter_resolution: strict_auto
  execution:
    max_steps: 3
    replan_every: 8
    replan_every_steps: 1
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - command: left_kiss
    - command: right_kiss
    - command: two_hand_kiss
    reset_policy: session_runner
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
    preferred_replan_every_steps: 1
  safety_profile:
    profile: default_simulation
    workspace_bounds: default
    stop_on_policy_timeout: true
  result:
    status: succeeded
    success: true
    num_steps: 0
    artifact_dir: artifacts/runtime/kiss_sequence_001
    metadata:
      message: arm_action:two_hand_kiss
      return_value: 3.0
      num_steps: 3
      final_status: {}
      artifacts: {}
- session_id: move_backward_001
  replan_attempt: 0
  goal_id: move_backward
  target_ref: g1_real_builtin
  skillruntime_ref: g1_builtin_command
  task_description: Move backward 0.5m.
  verification_profile: strict
  status: succeeded
  priority: normal
  updated_at: '2026-07-28T08:14:58.538953Z'
  claimed_by: runtime-watchdog@szh-MS-7D90
  claim_token: 0255fe16f0304d2ca66e25b69fd1b8b8
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 10.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    target_endpoint: targetws://127.0.0.1:9030
    policy_endpoint: openpi://policy-host:8000
    adapter_resolution: strict_auto
  execution:
    max_steps: 1
    replan_every: 8
    replan_every_steps: 1
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - command: move
      params:
        vx: -0.5
        vy: 0.0
        vyaw: 0.0
        duration_s: 1.0
    reset_policy: session_runner
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
    preferred_replan_every_steps: 1
  safety_profile:
    profile: default_simulation
    workspace_bounds: default
    stop_on_policy_timeout: true
  result:
    status: succeeded
    success: true
    num_steps: 0
    artifact_dir: artifacts/runtime/move_backward_001
    metadata:
      message: move
      return_value: 1.0
      num_steps: 1
      final_status: {}
      artifacts: {}
- session_id: move_forward_001
  replan_attempt: 0
  goal_id: move_forward
  target_ref: g1_real_builtin
  skillruntime_ref: g1_builtin_command
  task_description: Move forward 0.5m.
  verification_profile: strict
  status: succeeded
  priority: normal
  updated_at: '2026-07-28T08:15:36.778069Z'
  claimed_by: runtime-watchdog@szh-MS-7D90
  claim_token: cc7fa1cae369430598a9f80a5107d747
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 10.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    target_endpoint: targetws://127.0.0.1:9030
    policy_endpoint: openpi://policy-host:8000
    adapter_resolution: strict_auto
  execution:
    max_steps: 1
    replan_every: 8
    replan_every_steps: 1
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - command: move
      params:
        vx: 0.5
        vy: 0.0
        vyaw: 0.0
        duration_s: 1.0
    reset_policy: session_runner
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
    preferred_replan_every_steps: 1
  safety_profile:
    profile: default_simulation
    workspace_bounds: default
    stop_on_policy_timeout: true
  result:
    status: succeeded
    success: true
    num_steps: 0
    artifact_dir: artifacts/runtime/move_forward_001
    metadata:
      message: move
      return_value: 1.0
      num_steps: 1
      final_status: {}
      artifacts: {}
- session_id: kiss_sequence_002
  replan_attempt: 0
  goal_id: kiss_sequence
  target_ref: g1_real_builtin
  skillruntime_ref: g1_builtin_command
  task_description: 'Execute kiss sequence: left_kiss -> right_kiss -> two_hand_kiss.'
  verification_profile: strict
  status: succeeded
  priority: normal
  updated_at: '2026-07-28T08:41:54.594669Z'
  claimed_by: runtime-watchdog@szh-MS-7D90
  claim_token: cb8ddacc1e914082a4668274664ae0b2
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 10.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    target_endpoint: targetws://127.0.0.1:9030
    policy_endpoint: openpi://policy-host:8000
    adapter_resolution: strict_auto
  execution:
    max_steps: 3
    replan_every: 8
    replan_every_steps: 1
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - command: left_kiss
    - command: right_kiss
    - command: two_hand_kiss
    reset_policy: session_runner
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
    preferred_replan_every_steps: 1
  safety_profile:
    profile: default_simulation
    workspace_bounds: default
    stop_on_policy_timeout: true
  result:
    status: succeeded
    success: true
    num_steps: 0
    artifact_dir: artifacts/runtime/kiss_sequence_002
    metadata:
      message: arm_action:two_hand_kiss
      return_value: 3.0
      num_steps: 3
      final_status: {}
      artifacts: {}
```
