# move-arm-by-ee Skill Demo

> 状态：MuJoCo profile 已完成端到端验收  
> 验证日期：2026-08-14  
> Skill 版本：`0.1.0`

本文说明如何通过 PAOS 显式启动 `move-arm-by-ee` Skill Runtime，并让 Agent 按
`SKILL.md` 将“将夹爪向前移动 5cm”转换为 Query + Action Tool 调用。

总体架构和核心概念见
[PAOS Skill Runtime 与 Forge Tool 架构（当前实现）](skill-runtime-tool-architecture.md)。

## 1. Demo 目标

该 Demo 验证以下完整链路：

```text
自然语言“将夹爪向前移动 5cm”
  -> PAOS Agent
  -> move-arm-by-ee SKILL.md
  -> motion.resolve_relative_pose Query
  -> absolute target_pose
  -> motion.move_pose Action
  -> MotionServer
  -> JointTrajectoryController
  -> MuJoCo
  -> terminal ToolResult
  -> Agent 回复
```

Demo 保持以下边界：

- Agent 只处理任务语义、Tool 选择、参数组织和失败后的重新规划；
- Relative Pose Query 负责当前位姿、坐标系和相对位移解析；
- MotionServer 负责 IK、轨迹规划、执行编排、取消传播和最终残差验证；
- JointTrajectoryController 负责轨迹跟踪和 `JointCommand`；
- MuJoCo 负责仿真状态与动作；
- 高频 `JointState`、轨迹和 `JointCommand` 只在 Dora 数据面传输。

## 2. 当前可运行范围

PAOS 本地 Bundle 当前只声明一个可启动 profile：

```text
mujoco
```

Forge Runtime 示例源码还包含以下 dataflow：

- `dataflow.yaml`：仅 Gateway + 两个 Policy Endpoint 的逻辑图，不能完成运动；
- `dataflow.fake.yaml`：使用确定性 `skill_caller` 和 fake plant 的集成 smoke；
- `dataflow.mujoco.yaml`：当前 PAOS Bundle 实际使用并已验收；
- `dataflow.robot.yaml`：Agilex Piper 真机静态配置，未作为 PAOS 自动验收 profile。

不能因为源码存在 fake/robot dataflow，就认为它们已经在当前 `skill.yaml` 中安装为
PAOS profile。当前 `paos skill inspect` 只应显示 `mujoco`。

## 3. 本地安装布局

PAOS 使用两个相互独立的本地根目录。

### 3.1 Skill Bundle

```text
~/.PhyAgentOS/skills/move-arm-by-ee/
├── SKILL.md
└── skill.yaml
```

`SKILL.md` 是 Agent 的任务知识。`skill.yaml` 声明：

- required Tools：
  - `motion.resolve_relative_pose`
  - `motion.move_pose`
- Gateway：
  - `http://127.0.0.1:19002`
- MuJoCo dataflow；
- 七个 required binaries；
- Piper URDF 和 MJCF 资产。

当前验收使用的 `skill.yaml` 是本地已安装 Bundle 内容；源码中的内置 Skill 目录主要
提供 `SKILL.md`，尚未形成可由 `paos skill install` 发布和安装的完整 Bundle。Agent
加载同名 Skill 时，优先级为 workspace、installed、built-in，因此本地 installed
`SKILL.md` 可能覆盖内置版本。

### 3.2 Forge Runtime

```text
~/.PhyAgentOS/forge_runtime/
├── gateway
├── relative_pose_policy
├── motion_action_policy
├── motion_server
├── joint_trajectory_controller
├── mujoco_sim
├── image_viewer
└── examples/move_arm_by_ee_skill/
    ├── dataflow.mujoco.yaml
    ├── gateway.yaml
    ├── relative_pose_policy.yaml
    ├── motion_server.yaml
    ├── controller.yaml
    ├── simulator.yaml
    ├── image_viewer.yaml
    └── assets/
        ├── piper_with_gripper.urdf
        └── piper_mujoco/
```

当前 Runtime Manager 只消费已经存在的本地文件，不会自动下载缺失内容。未来的 Bundle
下载和 Forge Runtime 制品下载是两项独立 TODO。

外部部署过程可以生成 SHA-256 manifest 和备份，但当前 PAOS 启动只检查文件存在性和
可执行权限，不消费 SHA-256 manifest，也不会自动选择版本或回滚。

## 4. MuJoCo 七节点架构

```text
                          HTTP Tool API
PAOS Agent ------------------------------------+
                                               |
                                               v
                                         +-----------+
                                         |  gateway  |
                                         +-----+-----+
                                               |
                         +---------------------+--------------------+
                         |                                          |
                         v                                          v
              +------------------------+                +----------------------+
              | relative_motion_policy |                | motion_action_policy |
              | Query Endpoint          |                | Action Endpoint      |
              +-----------+------------+                +----------+-----------+
                          ^                                        |
                          | JointState                             | Dora Action
                          |                                        v
                          |                              +-------------------+
                          |                              |   motion_server   |
                          |                              +---------+---------+
                          |                                        |
                          |                                        v
                          |                              +-------------------+
                          +------------------------------| joint_trajectory  |
                          |                              |    controller     |
                          |                              +---------+---------+
                          |                                        |
                          | JointState                  JointCommand|
                          |                                        v
                          |                              +-------------------+
                          +------------------------------|      mujoco       |
                                                         +---------+---------+
                                                                   |
                                                               image/*
                                                                   v
                                                         +-------------------+
                                                         |   image_viewer    |
                                                         +-------------------+
```

七个物理进程：

1. `gateway`
2. `relative_motion_policy`
3. `motion_action_policy`
4. `motion_server`
5. `joint_trajectory_controller`
6. `mujoco`
7. `image_viewer`

### 4.1 gateway

提供 Gateway Tool API，加载 ToolSpec，并维护 Endpoint 注册、租约和 Action
ToolInvocation。

监听地址：

```text
http://127.0.0.1:19002
```

### 4.2 relative_motion_policy

提供：

```text
endpoint_id: motion.relative_pose
operation: resolve
semantics: query
```

它消费 MuJoCo `proprio_state`，用当前 JointState 做 FK，将相对位移解析成绝对
`target_pose`。

### 4.3 motion_action_policy

提供：

```text
endpoint_id: motion.server
operation: move_pose
semantics: action

endpoint_id: motion.server
operation: move_joints
semantics: action
```

它是 Forge Action Endpoint adapter，负责 Tool lifecycle 与 MotionServer Dora Action
之间的映射，不复制 IK 和轨迹规划。

### 4.4 motion_server

负责：

- 新鲜完整 JointState 校验；
- group、frame、goal 和 tolerance 校验；
- MovePose IK；
- 关节轨迹规划和时间参数化；
- 下游轨迹 Action；
- feedback、timeout 和 cancel 传播；
- 最终 JointState/FK 残差验证。

### 4.5 joint_trajectory_controller

跟踪 MotionServer 生成的轨迹，产生低层 JointCommand，并返回 trajectory
feedback/result。

### 4.6 mujoco

提供：

- `proprio_state`；
- JointCommand 执行；
- wrist/top/angle/left-pillar 四路图像。

该 profile 使用一个非奇异、留有前向工作空间的仿真 ready pose。全零 Piper 关节状态
接近运动学奇异点，保持 TCP 方向做前向平移时可能无法求解，因此不作为 Demo 启动状态。

### 4.7 image_viewer

订阅四路 MuJoCo 图像：

```text
image/hand
image/top
image/angle
image/left_pillar
```

当前 Runtime readiness 只检查该节点随 Dora flow 正常启动；尚未提供 Agent-facing
逐帧计数或图像健康 Tool。

## 5. Tool 契约

### 5.1 `motion.resolve_relative_pose`

ToolSpec：

```text
tool_id: motion.resolve_relative_pose
endpoint_id: motion.relative_pose
operation: resolve
semantics: query
```

主要输入：

```json
{
  "group_name": "piper_arm",
  "target_frame": "tcp",
  "reference": "current",
  "translation_frame": "base",
  "translation_m": {
    "x": 0.05,
    "y": 0.0,
    "z": 0.0
  },
  "orientation_mode": "preserve",
  "axis_angle_rad": null,
  "max_state_age_ms": 200
}
```

主要输出：

```json
{
  "source_pose": {},
  "target_pose": {},
  "frames": {
    "reference_frame": "arm_base",
    "target_frame": "tcp",
    "translation_frame": "base",
    "rotation_frame": "tcp"
  },
  "state_age_ms": 1.0,
  "source_snapshot": {
    "version": 1,
    "received_monotonic_ns": 0,
    "age_ms": 1.0,
    "time_basis": "policy_receive_monotonic"
  }
}
```

输出中的 pose 包含 `x/y/z/qx/qy/qz/qw`。

Query 只返回坐标计算结果，不移动机器人。Query 和 Action 不是原子事务；机器人状态变化
后必须重新 Query。

### 5.2 `motion.move_pose`

ToolSpec：

```text
tool_id: motion.move_pose
endpoint_id: motion.server
operation: move_pose
semantics: action
```

主要输入：

```json
{
  "group_name": "piper_arm",
  "reference_frame": "arm_base",
  "target_frame": "tcp",
  "target_pose": {
    "x": 0.24,
    "y": 0.0,
    "z": 0.24,
    "qx": 0.0,
    "qy": 0.0,
    "qz": 0.0,
    "qw": 1.0
  },
  "velocity_scale": 0.5,
  "acceleration_scale": 0.5,
  "position_tolerance_m": 0.01,
  "orientation_tolerance_rad": 0.05
}
```

实际调用必须使用 Query 返回的完整 `target_pose`，示例数值不能替代实时 Query。

Action start 返回 `202 Accepted + invocation_id`。最终结果包含：

- `goal_id`；
- Motion error code 和 message；
- elapsed time；
- final pose；
- final position/orientation residual；
- final joint positions。

### 5.3 Frame 方向语义

当前 Piper Tool context 声明：

```text
forward:
  frame: arm_base
  axis: x
  sign: 1
```

因此“向前 5cm”解释为：

```text
translation_frame = base
translation_m.x = +0.05
```

Agent 必须读取实时 `robot_frame_profile`，不能凭训练知识猜测方向。如果 profile 未声明
某个自然语言方向，应先向用户澄清。

## 6. Agent 的实际调用顺序

`SKILL.md` 要求：

```text
1. forge_tool_context(motion.resolve_relative_pose)
2. forge_tool_context(motion.move_pose)
3. forge_tool_query(motion.resolve_relative_pose, relative arguments)
4. 从 Query 结果读取 absolute target_pose
5. forge_tool_start_action(motion.move_pose, absolute arguments)
6. 保存 invocation_id
7. forge_tool_action_status(invocation_id)
8. forge_tool_action_result(invocation_id)
9. 直到明确 terminal
```

PAOS bridge 工具是通用 Tool API adapter。`motion.move_pose` 是领域 Tool ID，不是一个
独立 Python Agent Tool 类。

## 7. 前置条件

需要：

- 当前 PAOS 代码或包含 `skill` 子命令的已安装 PAOS；
- `dora` 在 `PATH` 中；
- Skill Bundle 已放入 `~/.PhyAgentOS/skills/move-arm-by-ee`；
- Forge Runtime 七个二进制和所需资产已放入
  `~/.PhyAgentOS/forge_runtime`；
- `127.0.0.1:19002` 未被其他服务占用；
- 图形环境能够支持 image viewer；无图形环境时需要使用兼容的 viewer 配置。

检查当前 CLI 是否包含 Skill Runtime：

```bash
paos --help
```

应看到：

```text
skill  Manage installed Skill runtimes
```

## 8. 运行方式

### 8.1 已安装 PAOS

```bash
paos skill list
paos skill inspect move-arm-by-ee
paos skill start move-arm-by-ee --profile mujoco
paos skill status move-arm-by-ee
paos agent -m "将夹爪向前移动5cm"
paos skill stop move-arm-by-ee
```

也可以先进入交互式 Agent：

```bash
paos agent
```

然后输入：

```text
将夹爪向前移动5cm
```

### 8.2 从 PAOS 源码工作区运行

如果系统中的 `paos` 是旧安装版本，应使用当前工作区：

```bash
uv run --extra dev paos skill inspect move-arm-by-ee
uv run --extra dev paos skill start move-arm-by-ee --profile mujoco
uv run --extra dev paos skill status move-arm-by-ee
uv run --extra dev paos agent -m "将夹爪向前移动5cm"
uv run --extra dev paos skill stop move-arm-by-ee
```

也可以把当前工作区安装到正在使用的 Python 环境，然后重新打开 shell 或执行
`hash -r`。

## 9. `paos skill start` 做了什么

启动命令不是简单执行一个 YAML。它会：

1. 从 installed Skill Catalog 加载 `skill.yaml`；
2. 严格验证 manifest 和安全相对路径；
3. 验证 `dora`；
4. 验证 dataflow；
5. 验证七个 required binaries 可执行；
6. 验证 URDF 和 MJCF 资产；
7. 检查 required environment；
8. 拒绝复用占据相同 Gateway 地址的非托管服务；
9. 启动或复用 Dora coordinator/daemon；
10. 设置 `FORGE_RUNTIME_BIN=~/.PhyAgentOS/forge_runtime`；
11. 从 dataflow 所在目录启动具名 Dora flow；
12. 等待 flow running；
13. 等待 Gateway `GET /tools`；
14. 等待两个 required Tool contexts ready；
15. 将 Runtime 状态原子更新为 `running`。

启动成功输出类似：

```text
Skill move-arm-by-ee is running
profile=mujoco
flow=paos-move-arm-by-ee-mujoco
```

## 10. 状态与日志

检查状态：

```bash
paos skill status move-arm-by-ee
```

健康状态应满足：

```text
State: running
Dora flow: paos-move-arm-by-ee-mujoco (running)
Gateway GET /tools: ready
Tool context motion.resolve_relative_pose: ready
Tool context motion.move_pose: ready
```

查看日志：

```bash
paos skill logs move-arm-by-ee
paos skill logs move-arm-by-ee --lines 300
```

日志包括：

- PAOS Runtime 生命周期日志；
- Dora flow 启动日志；
- 节点 ready/exit；
- Gateway HTTP 请求；
- MuJoCo 和 Motion 节点输出。

## 11. 停止与取消

正常停止：

```bash
paos skill stop move-arm-by-ee
```

如果仍有未对账 Action，PAOS 会拒绝停止：

```text
Runtime has non-terminal Tool invocation(s)
```

应先：

1. 查询 invocation status；
2. 查询 result；
3. 必要时请求 cancel；
4. 继续查询直到明确 terminal；
5. 再停止 Skill Runtime。

应急管理员覆盖：

```bash
paos skill stop move-arm-by-ee --force
```

`--force` 不是正常机器人取消协议。cancel accepted 和 HTTP timeout 都不能证明物理运动
已经停止。

停止后应看到：

```text
State: stopped
Dora flow: paos-move-arm-by-ee-mujoco (down)
Gateway GET /tools: unavailable
```

Skill stop 只停止该具名 flow，保留共享 Dora coordinator/daemon。

## 12. 已完成验收

2026-08-14 的实际验收流程：

```text
paos skill start move-arm-by-ee --profile mujoco
paos skill status move-arm-by-ee
paos agent -m "将夹爪向前移动5cm"
paos skill stop move-arm-by-ee
```

验收结果：

- Agent 读取实时 ToolSpec 和 Frame Profile；
- `forward` 被解析为 `arm_base/+X`；
- Query 返回最新 source/target pose；
- Action 被 Gateway 接纳；
- MotionServer 完成 IK、轨迹执行和最终残差验证；
- Action terminal status 为 `succeeded`；
- 最终位置误差约 `8.25mm`；
- 最终方向误差约 `0.026rad`；
- Skill stop 后 Gateway 端口关闭；
- Dora flow 清理完成；
- 共享 Dora coordinator/daemon 保留。

image viewer 随 flow 正常启动并订阅四路图像，但当前没有独立的逐帧接收计数验收接口。

## 13. 常见故障

### 13.1 `No such command 'skill'`

原因：shell 调用了修改前安装的旧 `paos`，而不是当前源码或新安装版本。

检查：

```bash
which paos
paos --version
paos --help
```

源码工作区使用：

```bash
uv run --extra dev paos skill inspect move-arm-by-ee
```

### 13.2 Gateway 地址已占用

Runtime Manager 不会接管未知服务。检查并停止占用 `127.0.0.1:19002` 的旧 Gateway 或
旧 Dora flow，然后重新启动。

### 13.3 缺少二进制或资产

`start` 的 preflight 会给出相对于 `~/.PhyAgentOS/forge_runtime` 的缺失路径。当前不会
自动下载，必须先完整安装 Runtime Artifact Set。

### 13.4 Dora flow 未运行

执行：

```bash
paos skill logs move-arm-by-ee --lines 300
dora list
```

优先检查最先退出的节点；其余节点可能只是级联失败。

### 13.5 Tool context 不 ready

可能原因：

- Endpoint 尚未注册；
- Endpoint lease 过期；
- provider route 配置错误；
- JointState 尚未到达或已过期；
- ToolSpec 与 Endpoint descriptor 不一致。

查看 Gateway 和对应 Policy Node 日志。

### 13.6 IK 失败

不要对相同不可达目标盲目重试。重新 Query 当前状态，并根据错误：

- 减小位移；
- 检查 frame 语义；
- 检查初始姿态和工作空间；
- 请求用户修改目标。

Demo 已配置非奇异启动姿态，但这不代表任意相对目标都可达。

### 13.7 Action 已 accepted 但没有完成

继续使用 invocation ID 查询 status/result。不要把 `202 Accepted` 当作成功，也不要在
`unknown` 后无条件重试。

## 14. 安全与能力限制

当前 Demo：

- Gateway 没有应用层鉴权，因而必须保持 loopback 监听；若改为 `0.0.0.0`，必须增加
  防火墙、认证和访问控制；
- 没有碰撞检测；
- 没有 PlanningScene；
- 没有 OMPL；
- 没有 Cartesian path；
- 没有 streaming servo；
- 没有证明 image viewer 每帧健康的 Tool；
- 没有任务级外部 Completion/Verification Engine；
- 没有通用跨 Tool Resource/Control Manager。

MuJoCo 成功不代表真机可直接运行。真机 profile 必须额外完成：

- CAN 和驱动配置；
- 工作空间清空；
- 机械限位检查；
- 急停；
- 初始/回收位姿；
- 碰撞风险评估；
- 现场人工监护；
- Runtime artifact 和配置版本审核。

禁止 Agent 绕过 Tool 链路直接发送 JointCommand、轨迹点或底层驱动命令。

## 15. 当前相关文件

PAOS：

```text
PhyAgentOS/skill_runtime/
PhyAgentOS/forge/tool_client.py
PhyAgentOS/agent/tools/forge_tool_api.py
PhyAgentOS/agent/skills.py
PhyAgentOS/agent/context.py
PhyAgentOS/agent/loop.py
PhyAgentOS/cli/commands.py
```

安装约定：

```text
~/.PhyAgentOS/skills/move-arm-by-ee/
~/.PhyAgentOS/forge_runtime/examples/move_arm_by_ee_skill/
```

Forge Runtime 示例：

```text
forge_runtime/examples/move_arm_by_ee_skill/
```
