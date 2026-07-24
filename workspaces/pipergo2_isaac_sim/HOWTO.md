# PiperGo2 Isaac Sim — 带 GUI 窗口联调

## 前提

1. **`asserts/` 场景资产**（已链到 PhyAgentOS3；若缺失：`ln -sf /home/zyserver/work/my_project/PhyAgentOS3/asserts asserts`）
2. **本机 Isaac Sim**：`/home/zyserver/isaacsim3`（GUI 配置已写入 `*_gui.json`）
3. **DISPLAY**：桌面 `:1`（SSH 无桌面时需 X11 转发或 VNC）

---

## 一、PiperGo2 单机 — 看窗口里「走到 desk」

### 终端 A（开 Isaac 窗口，保持不关）

```bash
cd /home/zyserver/work/my_project/new/PhyAgentOS
conda activate paos
export DISPLAY=:1

bash scripts/start_isaacsim_gui.sh pipergo2 9003
```

等到：
- 弹出 **Isaac Sim 窗口**（Merom 场景 + PiperGo2）
- 终端出现：`Isaac Sim TargetWS server listening on targetws://0.0.0.0:9003`

> 首次启动可能要 **3–10 分钟**。**终端 A 请一直保持运行** — session 跑完后窗口不会关，可继续在终端 B 发下一条任务。

### 终端 B（发导航命令）

```bash
cd /home/zyserver/work/my_project/new/PhyAgentOS
conda activate paos

python scripts/run_runtime_watchdog.py \
  --workspace workspaces/pipergo2_isaac_sim \
  --environment-workspace ~/.PhyAgentOS/workspace \
  --session-id sess_piper_language_nav \
  --once
```

终端 A 里应看到 rollout 日志（`step language` / `navigate_to_named`），窗口里狗会走向 desk。

**其它可看效果的 session：**

| session_id | 效果 |
|------------|------|
| `sess_piper_language_describe` | 描述场景（基本不动腿） |
| `sess_piper_action_arm` | 机械臂关节动一下 |

---

## 二、Merom 多机器人 — 导航 + Franka 抓取

### 终端 A（多机场景）

```bash
bash scripts/start_isaacsim_gui.sh merom 9003
```

### 终端 B

```bash
# Piper 走到 desk
python scripts/run_runtime_watchdog.py \
  --workspace workspaces/merom_isaac_sim \
  --session-id sess_merom_piper_nav --once

# Franka 抓放（需终端 A 已是 merom 场景）
python scripts/run_runtime_watchdog.py \
  --workspace workspaces/merom_isaac_sim \
  --session-id sess_merom_franka_pick_place --once
```

---

## 三、常见问题

| 现象 | 处理 |
|------|------|
| `scene file not found ... asserts/` | 执行 `ln -sf .../PhyAgentOS3/asserts asserts` |
| 黑屏 / 无窗口 | `export DISPLAY=:1`，确认本机有图形桌面 |
| 终端 B 立刻 failed | 看 `SESSIONS.md` 的 `result.error_message`；多数是没开终端 A 或 `:9003` 未监听 |
| 狗不动 / arm 几乎不动 | 臂控需 `sim_steps: 120+`；导航用 `sess_piper_language_nav` |

---

## 四、改任务内容

- **说什么 / 做什么**：改 `workspaces/.../SESSIONS.md` 里对应 session 的 `execution.steps`
- **desk 坐标**：改 `external/isaac_env/configs/pipergo2_manipulation_gui.json` 的 `waypoints`
- **改完 rollout 配置**：重启终端 A
