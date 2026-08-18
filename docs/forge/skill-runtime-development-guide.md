# PAOS Skill Runtime 协作开发指南

本文面向共同开发 PAOS Forge Skill、Policy Node、控制器和仿真节点的工程师，描述当前
已经落地的本地文件结构、`move-arm-by-ee` 九节点组成、仓库边界和开发验收流程。

资源服务的上传、下载和发布 API 尚未进入本阶段。未来每个 Node Bundle 和 Skill Bundle
都会作为不可变 `tar.gz` 同时发布到 GitHub Release 和后台对象存储；本地目录、manifest、
digest 和 lock 契约不会因此改变。

## 1. 三类开发对象

### 1.1 Skill Bundle

Skill Bundle 表达任务知识和运行编排，包含：

- Agent 使用的 `SKILL.md`；
- `skill.yaml`；
- 每个 profile 的 Dora dataflow 和节点配置；
- URDF、MJCF、mesh、纹理等 Skill 专属资产；
- 对所有 Node Bundle 的精确版本和 digest lock。

Skill 不实现 FK、IK、轨迹控制、Gateway 路由或仿真执行。

### 1.2 Node Bundle

一个 Node Bundle 对应一个可独立构建、版本化、校验和更新的 Forge/Dora 节点。归档根
包含 `node-manifest.json`、节点 entrypoint 及其私有文件。不同 Skill 可以复用同一
Node 版本，也可以锁定不同版本。

### 1.3 Skill Environment

PAOS 根据 Skill 的 node lock 在本地生成 profile 专用 environment：

```text
~/.PhyAgentOS/forge_runtime/environments/<skill>/<profile>/<lock-digest>/
├── runtime-lock.json
├── bin/
│   ├── gateway -> 已安装的精确 Gateway Node 版本
│   └── ...
└── launch/
    ├── assets -> 已安装 Skill Bundle 的 assets
    └── profiles/<profile>/
        ├── dataflow.yaml
        └── *.yaml -> 已安装 Skill Bundle 的配置
```

`launch/dataflow.yaml` 是 PAOS 生成的启动副本，其中 `${FORGE_RUNTIME_BIN}` 已替换为
绝对的 environment `bin` 路径。这样即使 Dora daemon 早已启动，也不会误用 daemon
进程继承的旧环境变量。下载归档中不携带任何符号链接。

## 2. 文件结构

### 2.1 Git 源码中的 Skill

```text
PhyAgentOS/PhyAgentOS/skills/forge-skill/move-arm-by-ee/
├── SKILL.md
├── skill.yaml
└── profiles/
    └── mujoco/
        ├── dataflow.yaml
        ├── gateway.yaml
        ├── relative_pose_policy.yaml
        ├── motion_server.yaml
        ├── controller.yaml
        ├── gripper_controller.yaml
        ├── simulator.yaml
        └── image_viewer.yaml
```

Piper 资产的权威源码位于 `robots/agilex_piper/assets/`。打包时通过 packager
`--overlay` 写入 Skill Bundle 的 `assets/`，避免在多个 Git 仓库重复保存约 129 MiB
模型；用户安装后的 Skill Bundle 仍然自包含。

### 2.2 安装后的 Skill

```text
~/.PhyAgentOS/skills/move-arm-by-ee/
├── SKILL.md
├── skill.yaml
├── profiles/mujoco/*.yaml
└── assets/
    ├── piper_with_gripper.urdf
    └── piper_mujoco/
```

dataflow、配置和 `required_assets` 都相对这个 Skill 根目录解析。

### 2.3 安装后的 Node

```text
~/.PhyAgentOS/forge_runtime/nodes/
└── <node-id>/
    └── versions/
        └── <artifact-id>/
            ├── node-manifest.json
            └── <binary 或 node 私有目录>
```

Node 不使用全局 `current`。`skill.yaml` 通过 `artifact_id/version/platform/arch/digest`
选择不可变版本，environment 为该 Skill 暴露稳定 entrypoint。

## 3. `move-arm-by-ee` 九节点

| Dora 节点 | 稳定 entrypoint | 权威代码仓/目录 | 责任 |
|---|---|---|---|
| `gateway` | `gateway` | `forge_gateway` | Tool 发现、Endpoint 租约、Query/Action 路由、HTTP lifecycle |
| `relative_motion_policy` | `relative_pose_policy` | `policy_node/relative_pose_policy_node` | 当前 TCP FK、坐标变换、相对位移解析为绝对 pose |
| `motion_action_policy` | `motion_action_policy` | `motion` | Forge Action lifecycle 到 MotionServer Dora Action 的适配 |
| `gripper_action_policy` | `gripper_action_policy` | `policy_node/gripper_action_policy_node` | `gripper.set_opening` Tool lifecycle 适配 |
| `motion_server` | `motion_server` | `motion` | IK、轨迹规划、执行编排、取消和最终残差验证 |
| `joint_trajectory_controller` | `joint_trajectory_controller` | `controls` | 机械臂轨迹跟踪和 JointCommand |
| `gripper_action_controller` | `gripper_action_controller` | `controls` | 夹爪位置控制、反馈、限位、stall 和 timeout |
| `mujoco` | `mujoco_sim` | `mujoco_sim` | MuJoCo 状态、动作和图像 |
| `image_viewer` | `image_viewer` | `tools/viewers/image_viewer` | MuJoCo 多路图像展示 |

Agent 只负责 Tool 选择、参数组织、顺序和失败后的重新规划，不直接发送轨迹或
JointCommand。

## 4. Gateway 权威仓库

Forge Tool Gateway 的唯一权威仓库是：

```text
forge_gateway/
├── main.py
├── scripts/build_pyinstaller.sh
└── src/forge_gateway/
```

`forge_gateway/src/forge_gateway/` 是该独立仓库采用的标准 Python src-layout，业务代码
写在这里是正确的；错误做法是在
`forge_runtime/packages/nodes/gateway/src/forge_gateway/` 的历史快照上继续开发。

当前 `move-arm-by-ee` 的构建和打包明确使用：

```text
forge_gateway/scripts/build_pyinstaller.sh
forge_gateway/dist/gateway
```

`forge_runtime/packages/nodes/gateway/` 仍被部分旧 dataflow 使用，目前仅作为兼容快照。
修改 Gateway 时不得同时维护两套实现；这些旧 dataflow 后续应迁移到独立
`forge_gateway` Node Bundle。

另外，`paos gateway` 是 PAOS 自身的 Agent/Channel 服务入口，不是 Forge Tool
Gateway，也不存在应替代 `forge_gateway` 的 `paos-gateway` 业务源码仓。

## 5. 核心仓库依赖

建议将以下仓库放在同一工作目录下，保持本文中的相对路径：

| 仓库/组件 | 是否是本 Skill 核心依赖 | 主要产物 |
|---|---:|---|
| `PhyAgentOS` | 是 | Agent、Skill Runtime、manifest、installer、CLI、Skill 源码 |
| `forge_runtime` | 是 | Node/Skill packager、部署脚本、Dora 集成示例 |
| `forge_gateway` | 是 | `gateway` |
| Forge protocol 仓 | 是 | `forge-msgs`、`forge-tool`、`forge-common` |
| `policy_node/relative_pose_policy_node` | 是 | `relative_pose_policy` |
| `policy_node/gripper_action_policy_node` | 是 | `gripper_action_policy` |
| `motion` | 是 | `motion_action_policy`、`motion_server` |
| `controls` | 是 | 两个控制器 |
| `mujoco_sim` | MuJoCo profile 必需 | `mujoco_sim` |
| `tools/viewers/image_viewer` | MuJoCo profile 必需 | `image_viewer` |
| `robots/agilex_piper` | 资产必需 | Piper URDF、MJCF；未来 robot profile 驱动 |

节点间 Tool wire contract 来自 Forge protocol 包，不能在单个节点仓内复制模型后独立
演进。修改消息或 lifecycle 时必须协调 Gateway、Policy Node、PAOS bridge 和相关测试。

## 6. 拉取 PhyAgentOS 后能否直接运行

需要区分两层：

### 6.1 PAOS Agent 基础功能

PhyAgentOS 仓库本身可以安装和运行基础 Agent：

```bash
python -m pip install -e ".[dev]"
paos onboard
paos agent
```

仍需配置模型 provider/API key。Forge 高层功能还需要外部 Gateway。

### 6.2 `move-arm-by-ee` Skill

只拉取 PhyAgentOS **不能开箱运行**该机器人 Skill，原因是：

- 九个 Node binary 属于独立仓库，不提交到 PhyAgentOS；
- Git 源码中的 Skill 不重复保存 Piper 大资产；
- 远程 Node/Skill Bundle 尚未发布；
- 运行依赖 Dora 及 MuJoCo/图形环境。

当前开发机可以通过同级源码仓构建并本地安装：

```bash
cd forge_runtime
./deploy_move_arm_by_ee_skill.sh
```

已有二进制时使用：

```bash
./deploy_move_arm_by_ee_skill.sh --skip-build
```

远程发布完成后，用户只需安装 PhyAgentOS，再由 PAOS 获取 Skill Bundle 及其 lock 指定的
Node Bundles，不需要拉取这些源码仓库。

## 7. 团队开发职责

### Skill 作者

修改：

- `SKILL.md`；
- `skill.yaml`；
- `profiles/<profile>/dataflow.yaml`；
- profile 配置；
- Skill 专属资产引用。

不得把算法实现复制进 Skill，也不得把 binary 放进 Skill Bundle。

### Node 作者

只在节点权威仓修改实现和测试，构建独立 binary，更新 Node 版本。Node 行为或 wire
contract 改变时必须提供对应测试，并通知 Skill 作者更新 lock。

### Skill Runtime 作者

维护 PhyAgentOS 中的 manifest parser、NodeInstaller、environment builder、
RuntimeManager、CLI、安全解包和测试，不实现机器人算法。

### 集成与发布维护者

维护 `forge_runtime/scripts/package_paos_archive.py`、
`deploy_move_arm_by_ee_skill.sh`、静态包索引和端到端验收。

## 8. 开发流程

### 8.1 创建或修改 Skill

1. 明确 Tool ID、输入输出、frame、单位、安全边界和 terminal 语义。
2. 确认能力应由已有 Node 提供，还是需要新增独立 Node。
3. 在 `PhyAgentOS/PhyAgentOS/skills/forge-skill/<skill>/` 中修改 Skill。
4. dataflow/config/assets 使用 Skill 根相对路径；binary 使用稳定 entrypoint 名。
5. `skill.yaml` 为每个 Node 固定 artifact/version/platform/arch/digest。
6. 运行 manifest、packager和 RuntimeManager 测试。
7. 本地安装后执行 profile 启停和 Tool readiness 验收。

### 8.2 修改 Node

1. 在权威节点仓修改代码和单元测试。
2. 执行该仓 build 脚本，产生 `dist/<entrypoint>`。
3. 递增 Node 版本和 `artifact_id`；同一 artifact ID 不允许对应不同内容。
4. 使用 node packager 生成 `node-manifest.json` 和确定性归档。
5. 更新 Skill node lock 和静态索引。
6. 重新生成 environment 并执行端到端验收。

### 8.3 本地统一构建和安装

```bash
cd forge_runtime
./deploy_move_arm_by_ee_skill.sh
```

该脚本会：

1. 调用各权威仓 build 脚本；
2. 生成九个独立 Node Bundle；
3. 通过 overlay 将 Piper 资产打入 Skill Bundle；
4. 逐个校验并安装 Node；
5. 安装 Skill；
6. 生成 MuJoCo environment。

### 8.4 验收

```bash
cd PhyAgentOS
paos skill inspect move-arm-by-ee
paos forge-node verify gateway gateway-0.2.0-linux-x86_64
paos skill start move-arm-by-ee --profile mujoco
paos skill status move-arm-by-ee
paos skill stop move-arm-by-ee
```

`status` 必须同时满足：

- Dora flow running；
- Gateway `/tools` ready；
- `motion.resolve_relative_pose` ready；
- `motion.move_pose` ready；
- `gripper.set_opening` ready。

## 9. 测试入口

```bash
# PAOS Skill Runtime、索引和 Forge bridge
cd PhyAgentOS
uv run --extra dev pytest -q \
  tests/test_skill_runtime_manifest.py \
  tests/test_skill_runtime_manager.py \
  tests/test_skill_runtime_cli.py \
  tests/test_forge_package_index.py \
  tests/test_forge_tool_tools.py

# Node/Skill 确定性打包和归档安全
cd forge_runtime
uv run python -m pytest -q tests/test_package_paos_archive.py

# Gateway
cd forge_gateway
uv sync --frozen --all-groups
uv run pytest -q
./scripts/build_pyinstaller.sh
```

此外，修改 motion、controls、policy、MuJoCo 或 Viewer 时，必须运行对应仓库测试，不能只
依赖 PAOS 集成测试。

## 10. Review 检查表

- 修改发生在权威仓，而不是兼容快照；
- Skill Bundle 没有 binary，Node Bundle 没有 Skill 编排；
- dataflow/config/assets 路径可搬迁且不包含本机绝对路径；
- Tool ID、frame 和 SI 单位与 live ToolSpec 一致；
- Node artifact ID 不复用不同内容；
- node digest、archive SHA-256 和 Skill lock 一致；
- 不依赖 flat `~/.PhyAgentOS/forge_runtime/<binary>`；
- 持久 Dora daemon 下仍能使用生成的绝对 launch dataflow；
- 单元测试、打包测试、MuJoCo readiness 和 clean stop 均通过。

## 11. 未来发布

未来发布链会为每个不可变 Node Bundle 和 Skill Bundle 记录：

- 版本、平台和架构；
- archive SHA-256 与大小；
- GitHub Release URL；
- 后台对象存储 URL；
- node/skill manifest digest。

PAOS 将按 Skill lock 下载缺失 Node，并使用内容寻址缓存去重。服务端上传、下载、权限和
对象存储部署将在资源服务阶段单独实现，不属于当前 Skill 开发流程。
