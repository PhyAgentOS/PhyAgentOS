# Runtime Skillruntimes — G1

```yaml
version: runtime_skill_registry_v1
skillruntimes:
  - id: g1_builtin_command
    runtime: CommandSimSkillRuntime
    runtime_kind: builtin
    loop_mode: builtin_command_loop
    agent_exposure: constrained_target_tools
    supported_target_kinds:
      - real_robot
    observation_contract:
      observation_type: empty
      empty_observation_allowed: true
    target_tool_policy:
      expose:
        - execute_step
        - execute_arm_action
      forbidden:
        - raw_sdk_command
    supports_chunk: false
    default_replan_every: 1
```
