# Isaac Sim TargetWS Server

Standalone TargetWS server wrapping Isaac Sim rollout (InternUtopia).

## Launch (Isaac conda env, repo root)

```bash
python PhyAgentOS/runtime/targets/remote/isaacsim/server.py \
  --config external/isaac_env/configs/pipergo2_manipulation.json --gui --port 9003
```

Merom multi-robot:

```bash
python PhyAgentOS/runtime/targets/remote/isaacsim/server.py \
  --config external/isaac_env/configs/merom_multi_robot.json --gui --port 9003
```

Runtime endpoint: `targetws://127.0.0.1:9003`

Legacy rollout WebSocket (unchanged): `python -m external.rollout --config ... --gui --port 8765`

## Agent tools

Command sessions use `execute_step` via `CommandSimSkillRuntime`:

- `{"text": "go to desk"}` — natural language routing
- `{"command": "navigate_to_named", "params": {"waypoint_key": "desk"}}`
- `{"mode": "control", "action": {...}}` — low-level control
