# Runtime Skillruntimes — Scout 2.0

```yaml
version: runtime_skill_registry_v1
skillruntimes:
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
