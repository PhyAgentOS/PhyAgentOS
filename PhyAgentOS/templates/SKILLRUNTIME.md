# Runtime Skills

```yaml
version: runtime_skill_registry_v1
skillruntimes:
  - id: openpi_sim_vla
    runtime: OpenPISkillRuntime
    runtime_kind: policy
    loop_mode: policy_closed_loop
    agent_exposure: none
    supported_target_kinds:
      - simulation
    policy:
      policy_client: dummy
      policy_adapter: policy_adapter://dummy_openpi_adapter
      supports_chunk: true
    observation_contract:
      observation_type: multimodal
      empty_observation_allowed: false
    supports_chunk: true
    default_replan_every: 5
    requires:
      sensors: []
      environment_outputs: []
      strict_environment_contract: true
    output_contract:
      action:
        action_space_id: dummy_policy_delta_eef_gripper_v1
        shape:
          - T
          - 7
        dtype: float32
        normalized: false
        representation: delta_eef_pose_gripper
        frame: base
        chunk:
          variable_T: true
          default_T: 4
          policy_hz: 20
    adapter_requirements:
      allowed_bridges:
        - bridge://safety_clamp
      forbidden: []
  - id: pi05_libero_remote
    runtime: OpenPISkillRuntime
    runtime_kind: policy
    benchmark:
      benchmark_id: libero
      execution_mode: policy_loop
      target_interface: rollout_episode_v1
      result_schema: benchmark_execution_result_v1
      reset_owner: session_runner
    loop_mode: policy_closed_loop
    agent_exposure: none
    supported_target_kinds:
      - simulation
      - real_robot
    policy:
      policy_client: openpi
      policy_adapter: policy_adapter://openpi_pi05_adapter
      supports_chunk: true
    observation_contract:
      observation_type: multimodal
      empty_observation_allowed: false
    supports_chunk: true
    default_replan_every: 5
    requires:
      sensors: []
      environment_outputs: []
      strict_environment_contract: true
    input_contract:
      images:
        - observation/image
        - observation/wrist_image
      state: observation/state
      prompt: prompt
    output_contract:
      action:
        action_space_id: libero_pi05_delta_eef_gripper_v1
        tensor_key: actions
        shape:
          - T
          - 7
        dtype: float32
        normalized: false
        representation: delta_eef_pose_gripper
        frame: base
        chunk:
          variable_T: true
          default_T: 50
          policy_hz: 20
    adapter_requirements:
      allowed_bridges:
        - bridge://safety_clamp
      forbidden:
        - implicit_shape_truncation
        - implicit_representation_cast
  - id: libero_target_benchmark
    runtime: LiberoBenchmarkSkillRuntime
    runtime_kind: builtin
    loop_mode: target_native_benchmark
    agent_exposure: none
    supported_target_kinds: [simulation]
    observation_contract:
      observation_type: multimodal
      empty_observation_allowed: false
    supports_chunk: false
    default_replan_every: 1
    requires:
      sensors: []
      environment_outputs: []
      strict_environment_contract: true
    adapter_requirements:
      allowed_bridges: []
      forbidden: []
    benchmark:
      benchmark_id: libero
      execution_mode: target_native
      target_interface: target_benchmark_job_v1
      result_schema: benchmark_execution_result_v1
      reset_owner: skillruntime
  - id: pipergo2_isaac_vla
    runtime: OpenPISkillRuntime
    runtime_kind: policy
    loop_mode: policy_closed_loop
    agent_exposure: none
    supported_target_kinds:
      - simulation
    policy:
      policy_client: openpi
      policy_adapter: policy_adapter://pipergo2_isaac_openpi_adapter
      supports_chunk: true
    observation_contract:
      observation_type: multimodal
      empty_observation_allowed: false
    supports_chunk: true
    default_replan_every: 4
    requires:
      sensors: []
      environment_outputs: []
      strict_environment_contract: false
    input_contract:
      images:
        - observation/image
        - observation/wrist_image
      state: observation/state
      prompt: prompt
    output_contract:
      action:
        action_space_id: pipergo2_isaac_joint_v1
        tensor_key: actions
        shape:
          - T
          - 8
        dtype: float32
        normalized: false
        representation: joint_position
        frame: robot_base
        chunk:
          variable_T: true
          default_T: 4
          policy_hz: 20
    adapter_requirements:
      allowed_bridges:
        - bridge://safety_clamp
      forbidden: []
  - id: pipergo2_command_sim
    runtime: CommandSimSkillRuntime
    runtime_kind: builtin
    loop_mode: builtin_command_loop
    agent_exposure: constrained_target_tools
    supported_target_kinds:
      - simulation
    observation_contract:
      observation_type: multimodal
      empty_observation_allowed: false
    target_tool_policy:
      expose:
        - execute_step
      forbidden: []
      require_tool_schema_validation: true
      require_action_validation: false
      require_target_side_validation: true
    supports_chunk: false
    default_replan_every: 1
    requires:
      sensors: []
      environment_outputs: []
      strict_environment_contract: false
    adapter_requirements:
      allowed_bridges: []
      forbidden: []
  - id: behavior1k_vla
    runtime: OpenPISkillRuntime
    runtime_kind: policy
    loop_mode: policy_closed_loop
    agent_exposure: none
    supported_target_kinds:
      - simulation
    policy:
      policy_client: dummy
      policy_adapter: policy_adapter://b1k_dummy_policy_adapter
      supports_chunk: true
    observation_contract:
      observation_type: multimodal
      empty_observation_allowed: false
    supports_chunk: true
    default_replan_every: 1
    requires:
      sensors: []
      environment_outputs: []
      strict_environment_contract: true
    input_contract:
      images:
        - observation/head_rgb
        - observation/left_wrist_rgb
        - observation/right_wrist_rgb
      state: observation/state
      prompt: prompt
    output_contract:
      action:
        action_space_id: behavior1k_r1pro_joint_v1
        tensor_key: actions
        shape:
          - T
          - 23
        dtype: float32
        normalized: false
        representation: joint_position
        frame: robot
        chunk:
          variable_T: true
          default_T: 1
          policy_hz: 20
    adapter_requirements:
      allowed_bridges:
        - bridge://safety_clamp
      forbidden: []
  - id: go2_builtin_command
    runtime: CommandSimSkillRuntime
    runtime_kind: builtin
    loop_mode: builtin_command_loop
    agent_exposure: constrained_target_tools
    supported_target_kinds:
      - real_robot
    observation_contract:
      observation_type: empty
      empty_observation_allowed: true
      empty_observation_semantics: Go2 builtin command sessions do not require observation data.
    target_tool_policy:
      expose:
        - execute_step
      forbidden:
        - raw_sdk_command
        - reset
        - close
        - disable_safety
      require_tool_schema_validation: true
      require_action_validation: true
      require_target_side_validation: true
      require_operator_override_for_real_robot: false
      allow_reset_by_agent: false
      allow_close_by_agent: false
    supports_chunk: false
    default_replan_every: 1
    requires:
      sensors: []
      environment_outputs: []
      strict_environment_contract: false
    output_contract:
      action:
        action_space_id: go2_builtin_command_v1
        shape:
          - 1
          - 1
        dtype: object
        normalized: false
        representation: builtin_command
        frame: robot_base
        chunk:
          variable_T: false
          default_T: 1
          policy_hz: 10
    adapter_requirements:
      allowed_bridges: []
      forbidden:
        - raw_sdk_command
        - action_chunk_control
  - id: scout2_builtin_command
    runtime: CommandSimSkillRuntime
    runtime_kind: builtin
    loop_mode: builtin_command_loop
    agent_exposure: constrained_target_tools
    supported_target_kinds:
      - real_robot
    observation_contract:
      observation_type: multimodal
      empty_observation_allowed: false
    target_tool_policy:
      expose:
        - execute_step
      forbidden:
        - raw_ros2_command
        - disable_safety
    supports_chunk: false
    default_replan_every: 1
```
