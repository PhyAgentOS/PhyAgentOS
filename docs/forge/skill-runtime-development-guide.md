# PAOS Skill Runtime 协作开发指南

本文说明 Skill Runtime 的文件结构、九节点链路、仓库边界和最短开发流程。

当前安装和 MuJoCo 运行链已经实现。正式资源服务尚未上线；过渡期可使用已有的
`move-arm-by-ee` 离线 Quick Start 包。未来各节点 CI 将预构建 Node Bundle 并发布到
GitHub Release/对象存储，PAOS 只负责下载、校验、安装和运行。

## 1. 文件结构

- Skill Bundle：`SKILL.md`、`skill.yaml`、profile dataflow/配置和 Skill 专属资产。
- Node Bundle：单个版本的 Forge/Dora entrypoint、私有文件和
  `node-manifest.json`。
- Skill Environment：PAOS 按 Skill node lock 生成的不可变运行视图。

源码中的 Skill：

```text
PhyAgentOS/PhyAgentOS/skills/forge-skill/move-arm-by-ee/
├── SKILL.md
├── skill.yaml
└── profiles/mujoco/
    ├── dataflow.yaml
    └── *.yaml
```

Piper URDF/MJCF 位于 `robots/agilex_piper/assets/`，打包时写入 Skill Bundle。

安装后：

```text
~/.PhyAgentOS/
├── skills/move-arm-by-ee/
└── forge_runtime/
    ├── nodes/<node-id>/versions/<artifact-id>/
    └── environments/move-arm-by-ee/mujoco/<lock-digest>/
        ├── runtime-lock.json
        ├── bin/
        └── launch/
```

## 2. 九节点链路

1. `gateway`：`forge_gateway`，Tool 发现、租约和路由。
2. `relative_motion_policy`：`relative_pose_policy_node`，TCP FK 与相对位姿解析。
3. `motion_action_policy`：`motion`，Motion Action Tool 适配。
4. `gripper_action_policy`：`gripper_action_policy_node`，夹爪 Tool 适配。
5. `motion_server`：`motion`，IK、规划、执行和终态验证。
6. `joint_trajectory_controller`：`controls`，机械臂轨迹跟踪。
7. `gripper_action_controller`：`controls`，夹爪位置控制和反馈。
8. `mujoco`：`mujoco_sim`，仿真状态、动作和图像。
9. `image_viewer`：`tools/viewers/image_viewer`，多路图像显示。

Agent 使用：

- `motion.resolve_relative_pose`
- `motion.move_pose`
- `gripper.set_opening`

Agent 只组织 Tool 参数和顺序，不直接生成轨迹或 JointCommand。

## 3. 仓库边界

Gateway 唯一权威仓库是 `forge_gateway/`，实现采用标准 Python src-layout：

```text
forge_gateway/
├── main.py
├── scripts/build_pyinstaller.sh
└── src/forge_gateway/
```

不得继续在 `forge_runtime/packages/nodes/gateway/` 的历史快照开发 Gateway。

核心仓库：

- `PhyAgentOS`：Agent、Skill Runtime、CLI、Skill 源码；
- `forge`：`forge-msgs`、`forge-tool`、`forge-common`；
- `forge_gateway`、`motion`、`controls`；
- 两个 `policy_node` 仓；
- `mujoco_sim`、`image_viewer`、`robots/agilex_piper`。

修改 Tool wire contract 时必须同步 Gateway、Policy Node、PAOS bridge 和测试。

## 4. 开发流程

修改 Skill：

1. 定义 Tool、frame、SI 单位和失败语义。
2. 修改 `SKILL.md`、`skill.yaml`、dataflow/config。
3. 路径相对 Skill 根目录，binary 使用稳定 entrypoint。
4. 固定每个 Node 的 artifact/version/platform/arch/digest。
5. 重新打包并执行 readiness 验收。

修改 Node：

1. 只在节点权威仓修改代码和测试。
2. 运行该仓 build/release 脚本。
3. 由节点仓 CI 生成并发布预构建 Node Bundle。
4. 资源服务登记 artifact/version/platform/arch/digest，Skill 更新 lock。
5. 重新执行端到端验收。

## 5. 无资源服务 Quick Start

当前过渡性交付物：

```text
PhyAgentOS/dist/forge/quick-start/
├── move-arm-by-ee-quick-start-0.2.0-linux-x86_64.tar.gz
└── move-arm-by-ee-quick-start-0.2.0-linux-x86_64.tar.gz.sha256
```

目标机：

```bash
sha256sum -c move-arm-by-ee-quick-start-0.2.0-linux-x86_64.tar.gz.sha256
tar -xzf move-arm-by-ee-quick-start-0.2.0-linux-x86_64.tar.gz
cd move-arm-by-ee-quick-start-0.2.0-linux-x86_64
./quick_start.sh
paos agent -m "将夹爪向前移动5cm"
```

只部署、不启动：

```bash
./quick_start.sh --install-only
```

`quick_start.sh` 校验全部文件后，直接将 Skill 和九个 Node 部署到
`~/.PhyAgentOS`。PAOS 不增加离线安装接口，只使用已有的
`inspect/start/status/stop`。

目标机要求：Linux x86_64、Python 3.11/3.12、PhyAgentOS 基础依赖、Dora 0.4.1 和
桌面图形环境。

## 6. 验收

```bash
cd PhyAgentOS
uv run --extra dev pytest -q tests/test_skill_runtime_*.py

paos skill inspect move-arm-by-ee
paos skill start move-arm-by-ee --profile mujoco
paos skill status move-arm-by-ee
paos skill stop move-arm-by-ee
```

必须确认 Dora flow、Gateway 和三个 Tool context 全部 ready，并能够 clean stop。

Review 时检查：

- 修改位于权威仓，不是 Gateway 兼容快照；
- 路径不含开发机绝对路径；
- Tool ID、frame、单位与 live ToolSpec 一致；
- artifact ID、Node digest、archive SHA-256 和 Skill lock 一致。
