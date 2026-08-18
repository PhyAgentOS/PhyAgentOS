# PAOS Skill Runtime 与 Forge Tool 架构（当前实现）

> 状态：as-built  
> 验证日期：2026-08-14  
> 参考目标设计：`Forge_Skill_Tool_Runtime_Detailed_Design_v0.7`

本文描述当前代码已经实现并完成 MuJoCo 链路验收的架构。它不是目标架构的完整重述；
凡是尚未实现的能力均在文末 TODO 中明确列出。

## 1. 当前结论

当前系统已经跑通以下闭环：

```text
用户自然语言
  -> PAOS Agent
  -> 已激活 Skill 的知识与调用策略
  -> PAOS Forge Tool bridge
  -> Gateway Tool API
  -> ToolSpec 解析与 Endpoint 路由
  -> Query / Action Policy Endpoint
  -> MotionServer / Controller
  -> MuJoCo
  -> Action terminal result
  -> PAOS Agent
```

当前实现遵循一个关键原则：

> Skill 提供任务知识，ToolSpec 声明可调用能力，ToolCall 表达一次调用意图，
> Gateway 创建并管理真实 ToolInvocation，Endpoint 承接具体操作。

Skill 不是物理执行宏，Tool 也不等于 Dora Node。PAOS 不直接发送 `JointCommand`、
轨迹点或高频 `JointState`。

### 1.1 PAOS 当前有两条并列 Forge 执行面

当前代码中同时存在：

- 高层 Agent Session 面：`ForgeSessionOrchestrator`、`/agent/sessions` 和
  `forge_*` Agent tools；
- Gateway Tool API 面：`ForgeToolClient`、`/tools`、`/invocations` 和
  `forge_tool_*` Agent tools。

`move-arm-by-ee` 只使用第二条执行面，不复用 `ForgeSessionOrchestrator`。两条执行面
目前没有统一的 invocation、资源或端口协调层，不能把其中一条的生命周期保证自动套用到
另一条。

## 2. 当前系统边界

### 2.1 已实现

- 本地 Skill Bundle Catalog 与严格 `skill.yaml` 解析。
- `paos skill list/inspect/start/status/logs/stop`。
- Skill profile 对应 Dora dataflow 的显式启动、健康检查和停止。
- Runtime 激活后将完整 `SKILL.md` 注入 Agent 上下文。
- Runtime 激活后注册六个 Forge Tool bridge 工具。
- Gateway 静态 ToolSpec Catalog。
- Endpoint descriptor 注册、租约、实例路由和失效检测。
- Query 同步调用。
- Action start/status/result/cancel 生命周期。
- Action `invocation_id` 的 PAOS 本地持久化与停止门禁。
- Tool schema、readiness、Endpoint 状态和机器人 Frame Profile 的实时上下文。
- Query/Action Tool 与 Dora 高频数据面的隔离。
- 确定性 Skill Bundle/Node Bundle 打包、严格归档校验和逐文件 SHA-256 校验。
- 独立 Node 版本安装、Skill node lock 和 profile 专用 Skill Environment。
- RegistryClient、下载缓存以及 `paos skill install`/`paos forge-node install` 安装入口。

### 2.2 部分实现

- Runtime 当前能管理一个完整、预先声明的 resident Dora profile，但没有通用动态拓扑
  Planner。
- Gateway 已有 Action invocation authority，但还不是 v0.7 设计中的完整
  Resource/Control/Completion/Safety Runtime Core。
- 状态新鲜度由具体 Endpoint 和 Tool context 承担，尚无通用 State Manager。
- MotionServer 和 Endpoint 有串行执行/BUSY 约束，但尚无跨 Tool 的通用资源租约系统。
- Gateway 可以产生 Tool events；PAOS bridge 当前只暴露 context/query/start/status/result/
  cancel，没有 Agent-facing event stream 工具。
- Registry 下载和安装代码已经存在，但远端索引、GitHub Release 和对象存储尚未发布，
  因此 fresh clone 用户暂时不能仅凭 Skill 名称完成在线安装。

### 2.3 尚未实现

- Bundle 发布者签名、在线 search/update/remove、引用计数、垃圾回收和自动回滚。
- 按 GPU、Dora ABI、系统 ABI 和机器人型号进行通用制品选择。
- 通用 TaskPlan 数据模型和持久化 Planner。
- v0.7 中完整的 ExecutionPlan、Resource Manager、Control Manager、Session Manager、
  Completion Engine、Safety Supervisor 和动态 Topology Manager。
- Session semantics 在本条 Tool API 链路中的端到端接入。
- 多个 active Skill Runtime 的并行选择；当前 PAOS Agent 要求最多一个健康 Runtime。
- Tool 多实现选择、implementation fallback 和版本协商。
- Runtime 崩溃后的自动 invocation 对账与恢复。

## 3. 核心概念

### 3.1 Skill

Skill 是 Agent 的长期任务知识，不是 Runtime 直接执行的对象。

当前 Skill 的主体是 `SKILL.md`，用于描述：

- 何时使用该能力；
- 需要调用哪些 Tool；
- Tool 的推荐顺序；
- 参数、单位、坐标系和歧义处理；
- 失败、取消、超时和重新规划原则；
- 哪些底层数据或命令禁止由 Agent 直接发送。

例如 `move-arm-by-ee` 要求 Agent：

1. 读取 Query 和 Action Tool 的实时 context；
2. 将自然语言方向按 Frame Profile 解析；
3. 调用相对位姿 Query；
4. 把返回的绝对位姿传给 MovePose Action；
5. 使用 invocation ID 对账到 terminal result。

Skill 不拥有以下职责：

- Endpoint 路由；
- Action 状态机；
- 物理资源锁；
- IK、轨迹生成和控制周期；
- 机器人驱动；
- 真实执行是否停止的最终判断。

### 3.2 Skill Bundle

Skill Bundle 是 PAOS 本地可发现的安装单元。当前最小结构为：

```text
~/.PhyAgentOS/skills/<skill-name>/
├── SKILL.md
├── skill.yaml
├── profiles/<profile>/dataflow.yaml
├── profiles/<profile>/*.yaml
└── assets/
```

`skill.yaml` 当前声明：

- manifest 版本、Skill 名称和版本；
- `SKILL.md` 相对路径；
- Gateway URL；
- Runtime 启动后必须存在的 Tool ID；
- profile 对应的 Dora dataflow；
- 所需二进制、资产和环境变量；
- `artifacts.nodes` 中每个独立 Node Bundle 的精确版本与 digest lock。

profile 中的 dataflow 和 asset 相对 Skill Bundle 根解析；`required_binaries` 是稳定
entrypoint 名称。每个节点独立安装到
`~/.PhyAgentOS/forge_runtime/nodes/<node>/versions/<artifact-id>`。RuntimeManager
验证精确 lock 后，为 Skill/profile 创建不可变 environment `bin` 视图。

Skill Bundle 与运行中的 Skill Runtime 必须区分：

- Bundle 是静态安装内容；
- Runtime 是某个 Bundle profile 的一次本地激活状态；
- 停止 Runtime 不删除 Bundle；
- 删除 Bundle 也不应直接等价于停止仍在执行的机器人动作。

### 3.3 Skill Runtime

当前代码中的 Skill Runtime 是 PAOS 对一个完整 Dora profile 的显式生命周期管理，
而不是 v0.7 中完整的通用 Forge Runtime Core。

它负责：

- 校验 Bundle manifest；
- 校验 dataflow、二进制、资产和环境变量；
- 启动或复用 Dora coordinator/daemon；
- 设置 `FORGE_RUNTIME_BIN=<Skill environment>/bin` 和
  `PAOS_SKILL_ROOT=<Skill Bundle root>`；
- 启动具名 Dora flow；
- 等待 Gateway 和 required Tool contexts ready；
- 原子写入本地 Runtime 状态；
- 停止具名 flow；
- 在存在未对账 Action 时拒绝普通 stop。

本地状态位于：

```text
~/.PhyAgentOS/run/skills/<skill-name>.json
```

日志位于：

```text
~/.PhyAgentOS/logs/skills/
```

Runtime 状态为 `starting/running/stopping/stopped/failed`。`status` 会将持久状态与
Dora flow、Gateway 和 Tool context 的实时状态重新对账。

### 3.4 Tool

Tool 是 Agent 可调用的稳定领域能力。例如：

- `motion.resolve_relative_pose`
- `motion.move_pose`
- `motion.move_joints`
- `gripper.set_opening`

Tool 是语义与安全边界，不是进程、Dora Node 或 Python 函数的同义词。

一个 Tool 可以由一个 Endpoint operation 实现；多个 Tool 也可以绑定到同一个
Endpoint 的不同 operation。相反，轨迹控制器、原始传感器流、JointCommand 和 CAN
Driver 等内部节点默认不应成为 Agent-facing Tool。

当前调用方使用稳定 `tool_id`，不直接指定 provider 实例。

### 3.5 ToolSpec

ToolSpec 是 Gateway 中对一个 Tool 的当前可调用契约。它回答：

> 当前系统允许调用什么、参数是什么、返回什么、绑定到哪个 Endpoint operation？

当前 ToolSpec 包含：

- `tool_id`：Agent-facing 稳定标识；
- `implementation_id`：当前实现族标识；
- `endpoint_id`：逻辑 Endpoint；
- `operation`：Endpoint 内操作名；
- `semantics`：`query` 或 `action`；
- `description`；
- JSON `input_schema`；
- JSON `output_schema`；
- readiness 要求；
- `robot_frame_profile`。

Frame Profile 当前可声明：

- `robot_id`；
- `base_frame`；
- `tool_frame`；
- frame aliases；
- `direction -> {frame, axis, sign}`。

ToolSpec 是配置拥有的 caller-facing 契约，Endpoint descriptor 是 provider 拥有的
运行契约。Gateway 只有在二者的 `endpoint_id/operation/semantics` 一致时才允许调用。

当前 ToolSpec 尚未覆盖 v0.7 建议的通用 resources、control、completion、topology、
permission 和 safety policy。

### 3.6 Endpoint

Endpoint 是 Forge Tool 协议中的逻辑服务和故障域。它由稳定 `endpoint_id` 标识，并
通过 descriptor 声明自己提供的 operation。

当前示例包含：

```text
endpoint_id: motion.relative_pose
  operation: resolve
  semantics: query

endpoint_id: motion.server
  operation: move_pose
  semantics: action
  operation: move_joints
  semantics: action
```

Endpoint 的粒度按“共同部署、共同健康、共同并发和共同故障边界”划分，而不是每个动作
一个 Endpoint。

需要区分：

- `endpoint_id`：稳定逻辑身份；
- `endpoint_instance_id`：本次启动的具体 provider 实例；
- operation：该 Endpoint 中的一项能力；
- Tool ID：对 Agent 稳定的能力名称。

Provider 通过租约向 Gateway 注册 descriptor。Gateway 按逻辑 Endpoint 解析当前活动
实例，并把 Action 固定到被选中的实例。普通调用方看不到也不能伪造
`endpoint_instance_id`。

### 3.7 Policy Node

Policy Node 是承载 Endpoint adapter 和领域逻辑的部署单元。它不是 Agent Tool 本身。

当前有两种模式：

- `relative_motion_policy` 在一个进程内包含
  `RelativePoseQueryEndpoint + RelativePoseResolver`；
- `motion_action_policy` 包含 Forge Action Endpoint adapter，并通过 Dora Action 调用
  独立 `MotionServer`。

因此 Endpoint 和 domain server 可以同进程，也可以跨进程。判断标准是领域复杂度和
复用边界，不是协议要求。`MotionServer` 仍可被非 Tool caller 复用，所以没有被强行
合并进 Endpoint adapter。

### 3.8 ToolCall

ToolCall 是 Agent 在一次 TaskPlan 中产生的临时调用意图：

```text
ToolCall = tool name + arguments + current conversation/task context
```

当前 PAOS 没有独立持久化的通用 `ToolCall`/`TaskPlan` 领域模型。实际存在两级调用：

1. LLM 调用 PAOS bridge 工具，例如 `forge_tool_start_action`；
2. bridge 参数中携带领域 `tool_id` 和 `arguments`，再调用 Gateway Tool API。

因此当前 Agent 看到的 PAOS 工具名是：

- `forge_tool_context`
- `forge_tool_query`
- `forge_tool_start_action`
- `forge_tool_action_status`
- `forge_tool_action_result`
- `forge_tool_cancel_action`

领域 Tool ID 作为参数传入 bridge。这样 PAOS 不需要为每一个动态 ToolSpec 注册一个
新的 Python Tool 类。

### 3.9 ToolInvocation

ToolInvocation 是 Gateway 对真实调用创建的运行对象，不等同于 ToolCall。

- ToolCall 是 Agent 的调用意图；
- ToolInvocation 是 Runtime/Gateway 的执行事实；
- 同一个任务可以产生多个 ToolCall；
- 重试必须产生新的 attempt，不能把不确定执行当作未执行。

Query 当前同步返回，不需要 Agent 长期轮询。Action 返回 `202 Accepted` 和
`invocation_id`，随后必须使用 status/result/cancel API 对账。

Action acceptance 只表示请求被接纳，不表示运动完成。cancel accepted 只表示取消请求
已接纳，也不表示机器人已经停止。HTTP timeout 或 `unknown` 不能作为安全停止证据。

### 3.10 ToolResult 与 TaskResult

ToolResult 只说明某个 ToolInvocation 的结果。它不自动等于用户任务成功。

例如 MovePose 返回成功说明：

- 下游轨迹执行成功；
- MotionServer 获得最终新鲜状态；
- FK 成功；
- 最终位置和方向残差满足 Tool 参数。

但“夹爪移动后是否避开障碍物”“是否完成抓取任务”仍可能需要更高层验证。当前 Demo
没有通用任务级 Completion Engine 或独立 Verifier。

## 4. 核心关系

```text
Skill
  └─ 推荐/约束多个 Tool

Tool
  └─ 由一个 ToolSpec 描述

ToolSpec
  └─ 绑定 endpoint_id + operation + semantics

Endpoint
  ├─ 注册 descriptor 和 lease
  ├─ 可提供一个或多个 operation
  └─ 由一个 Policy Node 承载

Agent
  └─ 依据 Skill 和实时 ToolSpec 生成 ToolCall

Gateway
  └─ 把 ToolCall 转成 Query 请求或 Action ToolInvocation

Policy Node / Domain Service
  └─ 执行 operation，并返回 response/event/result
```

一组常见误区：

- Skill 不等于 Tool：一个 Skill 通常编排多个 Tool。
- Tool 不等于 Endpoint：Tool 是 caller-facing 能力；Endpoint 是 provider-facing 服务。
- Tool 不等于 Node：Node 可以只是内部高频数据处理单元。
- ToolCall 不等于 ToolInvocation：前者是 Agent 意图，后者是执行记录。
- Endpoint 不等于 Server：Endpoint 是协议边界，Server/Resolver 是领域逻辑。
- cancel 不是独立领域 Tool：它是 Action ToolInvocation 的控制操作。

## 5. 当前分层架构

### 5.1 Agent 知识与规划层

```text
SkillsLoader
  -> workspace Skill
  -> installed Skill Bundle
  -> built-in Skill
```

优先级为 workspace、installed、built-in。带
`requires.runtime: [<skill-name>]` 的 Skill 只有在对应 Runtime 健康时才会完整注入
Agent context；未激活时只出现在 Skill summary 中并标记不可用。

当前任务编排由 LLM 根据 `SKILL.md` 和 Tool context 动态完成，没有独立 TaskPlan
执行器。

### 5.2 PAOS Runtime 生命周期层

```text
SkillCatalog
  -> SkillManifest
  -> RuntimeManager
  -> RuntimeStateStore
  -> ActiveSkillRuntime
```

`RuntimeManager` 管理完整 profile 的 Dora flow。`ActiveSkillRuntime` 为 Agent 提供：

- Gateway URL；
- `ForgeToolClient`；
- 持久化 invocation ID 集合；
- Runtime availability。

当前只允许一个健康 active Runtime 被注入同一个 PAOS Agent。

### 5.3 PAOS Forge Tool bridge

`ForgeToolClient` 使用 Gateway HTTP Tool API：

```text
GET  /tools
GET  /tools/{tool_id}
GET  /tools/{tool_id}/context
POST /tools/{tool_id}:invoke
GET  /invocations/{invocation_id}
GET  /invocations/{invocation_id}/result
POST /invocations/{invocation_id}/cancel
```

`forge_tool_context` 同时读取 ToolSpec 与动态 context，使 Agent 在调用前看到实时
schema、frame 语义和 readiness。

Action start 后 invocation ID 被写入 Runtime state。只有明确 terminal status/result 才
从集合移除。`unknown` 保留，因此普通 `paos skill stop` 会被拒绝。

### 5.4 Gateway Tool 控制面

Gateway 负责：

- ToolSpec discovery；
- Tool 参数 schema 校验；
- Endpoint descriptor 注册和 lease；
- Tool ID 到 Endpoint operation 的解析；
- provider 实例选择和 fencing；
- Query 路由；
- Action invocation、status、result、cancel 和 event；
- invocation/attempt 关联；
- Endpoint 失效后的 ambiguous/unknown 处理。

Gateway 不承载 JointState、控制 tick 或轨迹点等高频运动数据。

### 5.5 Policy 与运动数据面

```text
Gateway
  -> Relative Query Endpoint
       <- JointState
       -> absolute target pose

Gateway
  -> Motion Action Endpoint
       -> MotionServer
       -> JointTrajectoryController
       -> JointCommand
       -> Robot / Simulator
```

Query Tool 与后续 Action Tool 不是原子事务。Skill 要求在二者之间保持机器人静止，并
禁止在状态变化后复用旧 target pose。

## 6. 启动时序

```text
用户
  -> paos skill start <skill> --profile <profile>
  -> SkillCatalog 读取已安装 Bundle
  -> Manifest 严格校验
  -> RuntimeManager preflight
       - dora 可用
       - dataflow 存在
       - binaries 可执行
       - assets 存在
       - required environment 完整
  -> 拒绝占用 Gateway 地址的非托管实例
  -> 原子写入 starting
  -> 启动/复用 dora coordinator + daemon
  -> 设置 FORGE_RUNTIME_BIN=<environment>/bin 与 PAOS_SKILL_ROOT
  -> dora start --name paos-<skill>-<profile>
  -> 等待 flow running
  -> 等待 GET /tools
  -> 等待 required Tool contexts ready
  -> 原子写入 running
```

任一步失败都会尝试停止已启动 flow，并写入 `failed + last_error`。

## 7. Agent 调用时序

```text
用户自然语言
  -> PAOS 启动时发现唯一健康 ActiveSkillRuntime
  -> 注册六个 Forge bridge tools
  -> 完整注入该 Skill 的 SKILL.md
  -> Agent 调用 forge_tool_context(tool_id)
  -> PAOS 并行读取 ToolSpec + context
  -> Agent 根据 schema/frame profile 生成参数
  -> Query:
       forge_tool_query(tool_id, arguments)
       -> Gateway -> Query Endpoint -> 同步结果
  -> Action:
       forge_tool_start_action(tool_id, arguments)
       -> Gateway 创建 invocation -> 202 Accepted
       -> PAOS 持久化 invocation_id
       -> Agent status/result 轮询
       -> terminal result 后清除 invocation_id
```

## 8. 停止时序与安全语义

普通停止流程：

```text
paos skill stop <skill>
  -> 读取 Runtime state
  -> active_invocations 非空则拒绝
  -> 写入 stopping
  -> dora stop --name <flow> --grace-duration 5s
  -> 写入 stopped
```

`--force` 是管理员应急覆盖，不是正常 Action cancel。正常做法是：

1. 对已知 invocation 查询 status/result；
2. 必要时发送 cancel；
3. 继续对账直到明确 terminal；
4. 再停止 Runtime。

停止 Skill flow 不停止共享 Dora coordinator/daemon。

## 9. 与 v0.7 目标设计的关系

当前实现验证了 v0.7 的以下核心判断：

- Skill 与 Tool 分离；
- Skill Library 不进入高频执行数据面；
- ToolSpec 是 Agent-facing 稳定能力契约；
- Tool 绑定 Policy Endpoint，而不是简单映射所有 Dora Node；
- Query 和 Action 使用不同生命周期；
- Agent 不需要理解 Dora 内部高频图；
- ToolResult 不等同于 TaskResult。

当前实现对目标设计做了一个务实收敛：

- PAOS `RuntimeManager` 先管理静态 resident profile；
- Gateway 先承担 Tool Catalog、Endpoint 路由和 Action invocation authority；
- 领域状态、并发和终态验证先由 Endpoint/MotionServer 完成；
- 暂不引入完整通用 Forge Runtime Core。

因此不应在文档或 API 中声称已经实现 v0.7 的 Resource/Control/Session/Completion/
Safety/Topology 全部能力。

## 10. 本地制品供应链已实现；远端发布待上线

机器可读包索引、JSON Schema 和归档安全契约见
[PAOS Forge 包索引规范](paos-forge-packages_zh.md)。当前实现已经放弃单体
Runtime Artifact Set，使用两种独立制品：

```text
Skill Bundle
├── skill.yaml
├── SKILL.md
├── profiles/<profile>/dataflow.yaml + 配置
├── Skill 专属 URDF/MJCF/mesh/纹理
└── artifacts.nodes：每个 Node 的不可变 lock

Node Bundle
├── node-manifest.json
└── 一个独立版本的 entrypoint 与私有文件
```

机器人二进制、驱动、MuJoCo 和共享 Gateway 不复制到 Skill Bundle。体积可控且与任务
紧密相关的 URDF/MJCF/mesh 等资产跟随 Skill 打包，保证安装后的 Skill 自包含。

### 10.1 已实现的安装和校验

- packager 生成确定性 `tar.gz`、manifest、inventory 和逐文件 SHA-256；
- ArchiveValidator 拒绝绝对路径、路径逃逸、链接、特殊文件、Unicode/casefold 冲突、
  文件数/大小超限和压缩炸弹；
- SkillInstaller 原子安装 Skill Bundle，并保留被替换版本的备份；
- NodeInstaller 将每个 Node 安装到独立 `artifact_id` 目录并支持完整校验；
- `skill.yaml` 对每个 profile 锁定 Node 的 artifact/version/platform/arch/digest；
- SkillEnvironmentBuilder 为 Skill/profile/lock digest 生成不可变运行视图；
- RuntimeManager 从 environment 的稳定 `bin` entrypoint 启动 Dora dataflow；
- RegistryClient 和 DownloadCache 能下载 Skill/Node 制品；
- CLI 已提供 `paos skill install`、`paos forge-node install/verify`。

当前本地布局：

```text
~/.PhyAgentOS/
├── skills/<skill>/
├── forge_runtime/
│   ├── nodes/<node-id>/versions/<artifact-id>/
│   ├── environments/<skill>/<profile>/<lock-digest>/
│   └── cache/
├── run/skills/
└── logs/skills/
```

### 10.2 尚未上线的发布能力

静态索引中的 GitHub Release URL 和后台对象存储 URL 尚未填充，Registry 服务也未部署，
所以当前在线安装入口没有可供 fresh clone 用户消费的正式制品。开发环境仍通过
`forge_runtime/deploy_move_arm_by_ee_skill.sh` 构建、打包和本地安装。

后续发布阶段仍需：

- 将每个不可变 Node Bundle 和 Skill Bundle 发布到 GitHub Release 与对象存储；
- 提供按名称、版本、channel、平台和架构查询的 Registry API；
- 增加发布者签名、SBOM、provenance 和漏洞状态；
- 增加下载续传、镜像、离线导入、引用计数和垃圾回收；
- 增加在线 update/remove、失败自动回滚和高权限节点审批；
- 扩展 GPU、Dora ABI、Python/系统 ABI 和硬件型号兼容选择。

Skill lock 必须始终引用精确 Node 制品，不能使用模糊的“最新版本”。启动时即使本地
manifest 和 digest 校验已经通过，仍需重新检查可执行文件、Dora flow 和实时 Tool
context。未来的 Bundle 签名不能替代 Node 二进制签名，Node 验证也不能替代 Skill
发布者和任务知识的信任验证。

## 11. 其他优先 TODO

### P0：可恢复性与安全

- PAOS 重启后自动对账持久化 invocation ID；
- Endpoint/Gateway 重启后的明确 orphan/unknown 管理流程；
- stop 前自动提示或执行受控 reconciliation；
- Tool event/SSE 的 PAOS Agent bridge；
- Runtime 日志脱敏、大小限制和轮转；
- Runtime state 并发写锁，避免多个 PAOS 进程竞争。

### P1：Runtime Core

- 通用 Resource/Control lease；
- 通用 State Requirements；
- Completion/Verification Engine；
- Session semantics；
- safety policy 和外部 supervisor；
- Tool implementation 选择与 fallback；
- resident/activate/dynamic/standalone topology。

### P1：多 Skill 与多 Runtime

- 同时安装多个 Runtime 的选择规则；
- Gateway namespace/端口管理；
- Tool ID 冲突和版本解析；
- 共享 artifact 与共享 resident Endpoint；
- Agent 针对任务选择 Skill/Runtime，而不是要求唯一 active Runtime。

### P2：开发者体验

- `paos doctor` 检查安装、Dora、端口、Bundle 和 Runtime artifact；
- 生成和校验 `skill.yaml` 的 CLI；
- ToolSpec/Endpoint descriptor 一致性离线检查；
- 可复现的 E2E 测试 profile；
- installed PAOS 与源码开发命令的文档分离。

## 12. 当前代码入口

PAOS：

```text
PhyAgentOS/skill_runtime/manifest.py
PhyAgentOS/skill_runtime/catalog.py
PhyAgentOS/skill_runtime/state.py
PhyAgentOS/skill_runtime/manager.py
PhyAgentOS/skill_runtime/integration.py
PhyAgentOS/forge/tool_client.py
PhyAgentOS/agent/tools/forge_tool_api.py
PhyAgentOS/agent/skills.py
PhyAgentOS/agent/context.py
PhyAgentOS/agent/loop.py
PhyAgentOS/cli/commands.py
```

Gateway 与示例：

```text
forge_gateway/src/forge_gateway/
forge_runtime/examples/move_arm_by_ee_skill/
```

当前 Demo 的具体运行和排障见
[move-arm-by-ee Skill Demo](move-arm-by-ee-skill-runtime.md)。
