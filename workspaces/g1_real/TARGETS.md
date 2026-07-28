# Runtime Targets — G1

```yaml
version: runtime_target_registry_v1
targets:
  - id: g1_real_builtin
    target_class: remote
    target_kind: real_robot
    embodiment: unitree_g1
    enabled: true
    workspace: workspaces/g1_real
    supported_skillruntimes:
      - g1_builtin_command
    runtime:
      target_runtime: G1RemoteTargetProxy
      target_endpoint: targetws://127.0.0.1:9030
      target_adapter: target_adapter://g1_builtin_adapter
      runtime_contract_ref: configs/runtime/contracts/g1_builtin.runtime.yaml
    observation:
      observation_type: empty
      empty_observation_allowed: true
    perception:
      enabled: false
      strict_preflight: true
      sensor_config_ref: null
      perception_config_ref: null
      artifact_dir: null
    config:
      robot_ip: 192.168.137.1
      host_ip: 192.168.137.222
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
