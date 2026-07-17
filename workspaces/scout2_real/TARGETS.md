# Runtime Targets — Scout 2.0

```yaml
version: runtime_target_registry_v1
targets:
  - id: scout2_real_builtin
    target_class: remote
    target_kind: real_robot
    embodiment: scout2
    enabled: true
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
    perception:
      enabled: false
      strict_preflight: true
    config:
      scout_ip: 192.168.101.150
      ros_master_uri: http://192.168.101.150:11311
      action_dim: 2
      max_chunk_size: 1
      control_hz: 20
      safety_limits:
        linear_x: [-0.5, 0.5]
        angular_z: [-1.0, 1.0]
        duration_s: [0.1, 3.0]
```
