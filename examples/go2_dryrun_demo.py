"""Go2 Dry-Run 演示脚本

演示从自然语言到机器人控制的完整链路，无需真机。
每个步骤都有输出说明，适合展示和教学。
"""

import json
import sys
import time

# ============================================================
# 第一部分：展示架构
# ============================================================

def show_architecture():
    """展示整体架构"""
    print("=" * 70)
    print("  Go2 Dry-Run 演示 — 整体架构")
    print("=" * 70)
    print()
    print("  ┌─────────────────────────────────────────────────────────┐")
    print("  │  你说: \"让Go2站起来向前走一步然后趴下\"                     │")
    print("  └─────────────────┬───────────────────────────────────────┘")
    print("                    │ paos CLI")
    print("                    ▼")
    print("  ┌─────────────────────────────────────────────────────────┐")
    print("  │  AgentLoop (LLM)                                        │")
    print("  │  参考: EMBODIED.md + TARGETS.md + SKILLRUNTIME.md        │")
    print("  │  推理: \"站起来\" → stand_up, \"向前走\" → move(vx=0.3)       │")
    print("  └─────────────────┬───────────────────────────────────────┘")
    print("                    │ 结构化 YAML")
    print("                    ▼")
    print("  ┌─────────────────────────────────────────────────────────┐")
    print("  │  Watchdog → CommandSimSkillRuntime                      │")
    print("  │  遍历 execution.steps，逐条调用 execute_step             │")
    print("  └─────────────────┬───────────────────────────────────────┘")
    print("                    │ WebSocket + msgpack")
    print("                    ▼")
    print("  ┌─────────────────────────────────────────────────────────┐")
    print("  │  Go2 TargetWS Server (Dry-Run 模式)                      │")
    print("  │  模拟执行所有命令，返回成功结果                           │")
    print("  └─────────────────────────────────────────────────────────┘")
    print()
    print("  ⚠️  Dry-Run 模式不连接真实机器人，所有操作仅模拟")
    print()


# ============================================================
# 第二部分：模拟 Agent 推理
# ============================================================

def simulate_agent_thinking(user_input: str):
    """模拟 LLM Agent 的推理过程"""
    print("=" * 70)
    print("  第 1 步: Agent 接收你的自然语言")
    print("=" * 70)
    print()
    print(f"  👤 你说: \"{user_input}\"")
    print()
    print("  🤖 Agent 正在分析...")
    time.sleep(0.5)
    print()
    print("  ┌─ LLM 推理过程 ──────────────────────────────────────────┐")
    print("  │                                                         │")
    print("  │  1. 解析意图:                                           │")
    print("  │     → 起身动作: stand_up                                │")
    print("  │     → 移动动作: move (前进方向)                          │")
    print("  │     → 结束动作: stand_down                              │")
    print("  │                                                         │")
    print("  │  2. 检查安全约束 (EMBODIED.md):                          │")
    print("  │     → vx 必须在 [-0.5, 0.5] 之间 → 设置为 0.3            │")
    print("  │     → duration_s 必须在 [0.1, 1.0] 之间 → 设置为 0.5     │")
    print("  │     → 不需要 nav / vision → 符合约束                     │")
    print("  │                                                         │")
    print("  │  3. 生成结构化命令:                                      │")
    print("  │     → 写入 SESSIONS.md                                  │")
    print("  │                                                         │")
    print("  └─────────────────────────────────────────────────────────┘")
    print()


def show_generated_yaml():
    """展示生成的 YAML 命令"""
    print("=" * 70)
    print("  第 2 步: LLM 生成结构化命令")
    print("=" * 70)
    print()
    print("  📝 写入 SESSIONS.md:")
    print()
    yaml_content = """  ┌─ SESSIONS.md ─────────────────────────────────────────────┐
  │                                                           │
  │  session:                                                 │
  │    target: target://go2_real_builtin                     │
  │    skillruntime: skillruntime://go2_builtin_command       │
  │    execution:                                             │
  │      steps:                                               │
  │        - command: stand_up                                │
  │        - command: balance_stand                           │
  │        - command: move                                    │
  │            params:                                        │
  │              vx: 0.3                                      │
  │              vy: 0.0                                      │
  │              vyaw: 0.0                                    │
  │              duration_s: 0.5                              │
  │        - command: stop                                    │
  │        - command: stand_down                              │
  │                                                           │
  └───────────────────────────────────────────────────────────┘"""
    print(yaml_content)
    print()
    time.sleep(0.3)
    print("  ✅ 命令已生成，等待 Watchdog 调度...")
    print()


# ============================================================
# 第三部分：模拟执行
# ============================================================

def simulate_execution():
    """模拟执行每一步命令"""
    print("=" * 70)
    print("  第 3 步: Watchdog 调度执行")
    print("=" * 70)
    print()

    steps = [
        {
            "command": "stand_up",
            "desc": "站起",
            "delay": 1.5,
            "icon": "🦴",
            "detail": "机器人从趴下状态缓慢伸展四肢，重心前移，前足先触地，后足跟随，最终四足稳定站立",
        },
        {
            "command": "balance_stand",
            "desc": "平衡站立",
            "delay": 0.8,
            "icon": "⚖️",
            "detail": "进入主动平衡模式，IMU 开始实时调整关节角度，可抵抗轻微外力",
        },
        {
            "command": "move",
            "params": {"vx": 0.3, "vy": 0.0, "vyaw": 0.0, "duration_s": 0.5},
            "desc": "向前移动",
            "delay": 1.2,
            "icon": "🚶",
            "detail": "四足交替迈步，前进速度 0.3 m/s，持续 0.5 秒，约移动 15 厘米后自动停止",
        },
        {
            "command": "stop",
            "desc": "停止",
            "delay": 0.3,
            "icon": "🛑",
            "detail": "所有关节角速度归零，机器人保持当前姿态原地静止",
        },
        {
            "command": "stand_down",
            "desc": "趴下",
            "delay": 1.2,
            "icon": "😴",
            "detail": "重心后移降低，前足弯曲贴近地面，身体缓慢下放，最终四肢收于腹下呈趴卧姿态",
        },
    ]

    for i, step in enumerate(steps, 1):
        print(f"  [{i}/{len(steps)}] {step['icon']} 执行: {step['command']}")
        if "params" in step:
            print(f"      参数: {json.dumps(step['params'], ensure_ascii=False)}")
        print(f"      → {step['desc']}")
        print(f"      📋 {step['detail']}")
        time.sleep(step["delay"])
        print()

    # 最后总结
    print("-" * 70)
    print()
    print("  ✅ 全部 5 步执行完成！")
    print()
    print("  📊 执行统计:")
    print(f"     总步数: 5")
    print(f"     成功: 5")
    print(f"     失败: 0")
    print(f"     总耗时: ~6 秒 (模拟)")
    print(f"     安全状态: ok (所有参数在限制范围内)")
    print()


# ============================================================
# 第四部分：模拟 Agent 回复
# ============================================================

def show_agent_reply():
    """模拟 LLM Agent 的最终回复"""
    print("=" * 70)
    print("  第 4 步: Agent 向用户汇报")
    print("=" * 70)
    print()
    print("  🤖 Agent 回复:")
    print()
    print("  ┌─────────────────────────────────────────────────────────┐")
    print("  │                                                         │")
    print("  │  \"Go2 已经完成了所有动作：                              │")
    print("  │  1️⃣  从趴下站起来了                                       │")
    print("  │  2️⃣  进入平衡站立模式                                      │")
    print("  │  3️⃣  向前移动了约 15 厘米                                  │")
    print("  │  4️⃣  停止运动                                             │")
    print("  │  5️⃣  重新趴下回到初始姿态                                  │")
    print("  │                                                         │")
    print("  │  所有命令执行成功，机器人现在处于趴下状态。                │")
    print("  │  还需要做其他动作吗？                                     │")
    print("  │                                                         │")
    print("  └─────────────────────────────────────────────────────────┘")
    print()


# ============================================================
# 第五部分：对比演示
# ============================================================

def show_multi_turn_demo():
    """展示多轮对话交互"""
    print("=" * 70)
    print("  进阶演示: 多轮对话交互")
    print("=" * 70)
    print()

    dialogues = [
        {
            "user": "让Go2原地转个圈",
            "agent": "好的，正在执行旋转动作...",
            "commands": ["balance_stand", "move (vyaw=-0.5, duration=1.0)", "stop"],
        },
        {
            "user": "向左移动半步",
            "agent": "正在横向移动...",
            "commands": ["move (vy=0.2, duration=0.3)", "stop"],
        },
        {
            "user": "蹲下试试",
            "agent": "进入阻尼模式，关节释放...",
            "commands": ["damp"],
        },
        {
            "user": "站起来吧",
            "agent": "正在站起...",
            "commands": ["stand_up", "balance_stand"],
        },
    ]

    for i, d in enumerate(dialogues, 1):
        print(f"  --- 第 {i} 轮对话 ---")
        print()
        print(f"  👤 你: \"{d['user']}\"")
        print()
        time.sleep(0.3)
        print(f"  🤖 Agent: {d['agent']}")
        print()
        time.sleep(0.3)
        print(f"  🔧 执行命令:")
        for j, cmd in enumerate(d["commands"], 1):
            time.sleep(0.2)
            print(f"     [{j}] {cmd}  ✅")
        print()

    print("-" * 70)
    print()
    print("  ✅ 多轮对话演示完成")
    print()


# ============================================================
# 第六部分：安全机制演示
# ============================================================

def show_safety_demo():
    """展示安全机制"""
    print("=" * 70)
    print("  安全演示: Agent 拒绝危险操作")
    print("=" * 70)
    print()

    unsafe_requests = [
        ("让Go2以 5m/s 全速冲刺", "⚠️ 安全限制：最大速度 0.5m/s，已自动裁剪到 vx=0.5"),
        ("直接用 SDK 控制所有关节", "🚫 禁止：原始 SDK 命令不允许通过 Agent 调用"),
        ("让Go2 autonomous 跑出去", "🚫 不支持：当前版本不支持自主导航和长距离移动"),
    ]

    for i, (unsafe, response) in enumerate(unsafe_requests, 1):
        print(f"  危险请求 {i}: \"{unsafe}\"")
        print(f"  🤖 Agent: {response}")
        print()

    print("-" * 70)
    print()
    print("  ✅ 安全机制演示完成")
    print()


# ============================================================
# 主流程
# ============================================================

def main():
    """运行完整演示"""
    print()
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "Go2 Dry-Run 完整演示系统" + " " * 25 + "║")
    print("║" + " " * 10 + "无需真机 · 模拟全部流程 · 展示自然语言控制" + " " * 20 + "║")
    print("╚" + "=" * 68 + "╝")
    print()

    # 选择演示模式
    print("请选择演示模式:")
    print("  1. 完整流程演示（推荐）")
    print("  2. 多轮对话演示")
    print("  3. 安全机制演示")
    print("  4. 全部演示（1+2+3）")
    print()
    choice = input("请输入选项 (1/2/3/4): ").strip()

    print()
    show_architecture()

    if choice in ("1", "4"):
        simulate_agent_thinking("让Go2站起来向前走一步然后趴下")
        show_generated_yaml()
        simulate_execution()
        show_agent_reply()

    if choice in ("2", "4"):
        show_multi_turn_demo()

    if choice in ("3", "4"):
        show_safety_demo()

    print("=" * 70)
    print("  演示结束")
    print("=" * 70)
    print()
    print("  💡 下一步:")
    print("     1. 启动 Dry-Run 服务:                                             ")
    print("        conda run -n go2-sdk python server.py --dry-run")
    print("     2. 启动 PhyAgentOS 并输入自然语言                                ")
    print("        paos run \"让Go2站起来\"")
    print("     3. 连接真机时去掉 --dry-run 参数                                  ")
    print()


if __name__ == "__main__":
    main()
