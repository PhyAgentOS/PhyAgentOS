# Merom 多机器人 Isaac Sim — 联调说明

## 终端 A

```bash
python PhyAgentOS/runtime/targets/remote/isaacsim/server.py \
  --config external/isaac_env/configs/merom_multi_robot.json --gui --port 9003
```

## 终端 B 示例

```bash
python scripts/run_runtime_watchdog.py \
  --workspace workspaces/merom_isaac_sim \
  --environment-workspace ~/.PhyAgentOS/workspace \
  --session-id sess_merom_franka_pick_place \
  --once
```

同一 TargetWS，不同 session 通过 `TARGETS.md` 中的 **`robot_id`** 选择机器人。
