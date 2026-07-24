# Runtime Targets

```yaml
version: runtime_target_registry_v1
targets:
  - id: dummy_sim
    target_class: local
    target_kind: simulation
    enabled: false
    workspace: workspaces/dummy_sim
    supported_skillruntimes:
      - openpi_sim_vla
    runtime:
      target_runtime: DummySimTargetRuntime
      target_endpoint: null
      target_adapter: target_adapter://dummy_sim_adapter
      runtime_contract_ref: configs/runtime/contracts/dummy_sim.runtime.yaml
    observation:
      observation_type: multimodal
      empty_observation_allowed: false
    perception:
      enabled: false
      strict_preflight: true
      sensor_config_ref: configs/runtime/sensors/dummy_sim.sensors.yaml
      perception_config_ref: null
      artifact_dir: null
    config:
      action_dim: 7
      success_after_steps: 5
      image_size: 16
      state_dim: 8
      action:
        action_dim: 7
        chunk_size: 4
  - id: libero_real_remote
    target_class: remote
    target_kind: simulation
    enabled: false
    workspace: workspaces/libero_real
    supported_skillruntimes:
      - pi05_libero_remote
      - libero_target_benchmark
    benchmark_capabilities:
      - benchmark_id: libero
        suites: [libero_spatial, libero_object, libero_goal, libero_10]
        execution_modes:
          - mode: policy_loop
            interface: rollout_episode_v1
            reset_owner: session_runner
          - mode: target_native
            interface: target_benchmark_job_v1
            reset_owner: skillruntime
    runtime:
      target_runtime: LiberoRemoteTargetProxy
      target_endpoint: targetws://libero-host:9002
      target_adapter: target_adapter://libero_adapter
      runtime_contract_ref: configs/runtime/contracts/libero_real.runtime.yaml
    observation:
      observation_type: multimodal
      empty_observation_allowed: false
    perception:
      enabled: false
      strict_preflight: true
      sensor_config_ref: null
      perception_config_ref: null
      artifact_dir: null
    config:
      benchmark_name: libero_spatial
      task_id: 0
      init_state_id: 0
      camera_height: 256
      camera_width: 256
      action_dim: 7
      max_chunk_size: 50
      max_steps: 280
      num_steps_wait: 10
  - id: pipergo2_isaac_remote
    target_class: remote
    target_kind: simulation
    enabled: false
    workspace: workspaces/pipergo2_isaac_sim
    supported_skillruntimes:
      - pipergo2_isaac_vla
      - pipergo2_command_sim
    runtime:
      target_runtime: IsaacSimRemoteTargetProxy
      target_endpoint: targetws://127.0.0.1:9003
      target_adapter: target_adapter://isaacsim_adapter
      runtime_contract_ref: configs/runtime/contracts/isaacsim_pipergo2.runtime.yaml
    observation:
      observation_type: multimodal
      empty_observation_allowed: false
    perception:
      enabled: false
      strict_preflight: true
      sensor_config_ref: null
      perception_config_ref: null
      artifact_dir: null
    config:
      robot_id: ""
      rollout_reset_each_session: false
      action_dim: 8
      max_chunk_size: 50
      max_steps: 600
      image_size: 224
      state_dim: 8
      image_key: camera1
      wrist_image_key: camera2
      third_image_key: camera3
      action:
        action_dim: 8
        action_name: arm_joint_controller
        control_wrap: list
        chunk_size: 4
  - id: pipergo2_merom_sim
    target_class: remote
    target_kind: simulation
    enabled: false
    workspace: workspaces/merom_isaac_sim
    supported_skillruntimes:
      - pipergo2_command_sim
    runtime:
      target_runtime: IsaacSimRemoteTargetProxy
      target_endpoint: targetws://127.0.0.1:9003
      target_adapter: target_adapter://isaacsim_adapter
      runtime_contract_ref: configs/runtime/contracts/isaacsim_pipergo2.runtime.yaml
    observation:
      observation_type: multimodal
      empty_observation_allowed: false
    perception:
      enabled: false
      strict_preflight: true
    config:
      robot_id: pipergo2
      rollout_reset_each_session: false
      action_dim: 8
      max_chunk_size: 50
      observation:
        image_size: 224
        state_dim: 8
      action:
        action_dim: 8
        action_name: arm_joint_controller
        control_wrap: list
  - id: g1_merom_sim
    target_class: remote
    target_kind: simulation
    enabled: false
    workspace: workspaces/merom_isaac_sim
    supported_skillruntimes:
      - pipergo2_command_sim
    runtime:
      target_runtime: IsaacSimRemoteTargetProxy
      target_endpoint: targetws://127.0.0.1:9003
      target_adapter: target_adapter://isaacsim_adapter
      runtime_contract_ref: configs/runtime/contracts/isaacsim_pipergo2.runtime.yaml
    observation:
      observation_type: multimodal
      empty_observation_allowed: false
    perception:
      enabled: false
      strict_preflight: true
    config:
      robot_id: g1
      rollout_reset_each_session: false
      action_dim: 8
      observation:
        image_size: 224
        state_dim: 8
      action:
        pass_through_control: true
  - id: franka_merom_sim
    target_class: remote
    target_kind: simulation
    enabled: false
    workspace: workspaces/merom_isaac_sim
    supported_skillruntimes:
      - pipergo2_command_sim
    runtime:
      target_runtime: IsaacSimRemoteTargetProxy
      target_endpoint: targetws://127.0.0.1:9003
      target_adapter: target_adapter://isaacsim_adapter
      runtime_contract_ref: configs/runtime/contracts/isaacsim_pipergo2.runtime.yaml
    observation:
      observation_type: multimodal
      empty_observation_allowed: false
    perception:
      enabled: false
      strict_preflight: true
    config:
      robot_id: franka
      rollout_reset_each_session: false
      action_dim: 8
      observation:
        image_size: 224
        state_dim: 8
      action:
        pass_through_control: true
  - id: behavior1k_r1pro_sim
    target_class: remote
    target_kind: simulation
    enabled: false
    workspace: external/b1k_bench/workspaces/behavior1k_eval
    supported_skillruntimes:
      - behavior1k_vla
    runtime:
      target_runtime: Behavior1KRemoteTargetProxy
      target_endpoint: targetws://127.0.0.1:9004
      target_adapter: target_adapter://behavior1k_openpi_adapter
      runtime_contract_ref: configs/runtime/contracts/behavior1k_r1pro.runtime.yaml
    observation:
      observation_type: multimodal
      empty_observation_allowed: false
    perception:
      enabled: false
      strict_preflight: true
    config:
      task_name: turning_on_radio
      instance_id: 0
      action_dim: 23
      max_chunk_size: 50
      max_steps: 200
      chunk_size: 1
  - id: scout2_real_builtin
    target_class: remote
    target_kind: real_robot
    embodiment: scout2
    enabled: false                    # 使用时改为 true
    workspace: workspaces/scout2_real
    supported_skillruntimes:
      - scout2_builtin_command
    runtime:
      target_runtime: ScoutRemoteTargetProxy
      target_endpoint: targetws://127.0.0.1:9020
      target_adapter: target_adapter://scout_adapter
      runtime_contract_ref: configs/runtime/contracts/scout2_builtin.runtime.yaml
    observation:
      observation_type: multimodal
      empty_observation_allowed: false
      channels:
        - camera
        - odom
        - lidar
    perception:
      enabled: false
      strict_preflight: true
    config:
      scout_ip: 192.168.101.150         # 替换为你的 Scout IP
      ros_master_uri: http://192.168.101.150:11311
      network_interface: wlo1
      action_dim: 2                    # linear_x, angular_z
      max_chunk_size: 1
      control_hz: 20
      safety_limits:
        linear_x: [-0.5, 0.5]          # 前后速度 m/s
        angular_z: [-1.0, 1.0]         # 旋转速度 rad/s
        duration_s: [0.1, 3.0]         # 移动时长秒
  - id: go2_real_builtin
    target_class: remote
    target_kind: real_robot
    embodiment: unitree_go2
    enabled: false
    workspace: workspaces/go2_real
    supported_skillruntimes:
      - go2_builtin_command
    runtime:
      target_runtime: Go2RemoteTargetProxy
      target_endpoint: targetws://127.0.0.1:9010
      target_adapter: target_adapter://go2_builtin_adapter
      runtime_contract_ref: configs/runtime/contracts/go2_builtin.runtime.yaml
    observation:
      observation_type: empty
      empty_observation_allowed: true
      empty_observation_semantics: Go2 builtin command sessions do not require observation data.
    perception:
      enabled: false
      strict_preflight: true
      sensor_config_ref: null
      perception_config_ref: null
      artifact_dir: null
    config:
      robot_ip: 192.168.123.161
      host_ip: 192.168.123.222
      network_interface: enp4s0
      action_dim: 1
      max_chunk_size: 1
      control_hz: 10
      safety_limits:
        vx:
          - -0.5
          - 0.5
        vy:
          - -0.2
          - 0.2
        vyaw:
          - -0.5
          - 0.5
        duration_s:
          - 0.1
          - 1.0
```
