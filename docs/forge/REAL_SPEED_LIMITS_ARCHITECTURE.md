# PAOS 真实速度限制架构：RoboTwin Franka 与硬件 Franka

状态：设计基线（2026-09-06）  
范围：速度能力来源、规划约束、控制器执行、运行时证据和 PAOS 权威边界  
不在范围：为当前 route 选择一个新的经验速度、启动仿真运动、接入真实硬件

## 1. 决策摘要

PAOS 不定义全局 `0.20 m/s`、统一 `1.0 rad/s` 或
`execution_velocity_scale`。这些值没有来自 RoboTwin、SAPIEN、CuRobo、
libfranka 或 Franka 硬件控制器的权威来源，因此不能作为安全限制，也不能靠
反复调小参数获得 controller qualification。

真正的速度限制链路是：

```text
robot description / SDK / controller
        │  provider-owned limits + source identity
        ▼
MotionCapability artifact (immutable, versioned)
        │
        ├── planner constraints / provider-native trajectory retiming
        ▼
controller command and enforcement
        │
        ▼
observed q, dq, TCP state + controller status
        │
        ▼
Execution evidence / Verifier
```

PAOS 负责绑定、校验和记录这条链路，不在 Core 内重新实现机器人控制器。

## 2. 为什么旧的统一速度门禁是错误抽象

旧实现把以下三件不同的事混在了一起：

1. route waypoint 中的 `max_linear_speed_mps=0.20`；
2. 对 CuRobo 轨迹做统一 `1.0 rad/s` time dilation，再对发送给 SAPIEN 的
   velocity target 乘 `execution_velocity_scale`；
3. 用相邻 SAPIEN step 的 TCP 位移估计速度，超出 `0.20 m/s` 就终止。

它不能形成真实速度保证，原因如下：

- 数字不是由本体、planner、controller 或 benchmark 导出；
- `set_drive_velocity_target()` 是 articulation drive target，不是笛卡尔硬限速器；
- 缩放 velocity target 而不建立 position target、drive dynamics、timestep 与实际
  状态之间的闭环约束，不能证明 TCP 速度受限；
- 相邻 step 的 TCP 位移只是事后 measurement，适合诊断和 evidence，不能反向
  冒充 controller enforcement；
- 单个 `max_joint_speed_radps` 不能表达 Franka 七个关节不同的限制，更不能表达
  位置相关动态速度边界、加速度、jerk 和 effort；
- 为了越过一个无来源阈值反复调 scale，只会改变实验结果，不会补齐权威来源。

因此旧 route v3 和 route-input profile v2 被退役；历史 probe 产物保留为负证据，
不能继续审批或复用。

## 3. RoboTwin Franka 的实际链路

当前独立 RoboTwin20 环境使用 SAPIEN、CuRobo 和 MPlib，不包含
`libfranka`、`frankx`、`franka_ros` 或真实 Franka driver。证据边界为：

- `assets/embodiments/franka-panda/panda.urdf`：关节 position、velocity 和
  effort 描述；arm joint 1–4 的 URDF velocity 为 `2.175 rad/s`，joint 5–7
  为 `2.610 rad/s`，finger joint 为 `0.2`；
- `assets/embodiments/franka-panda/curobo.yml`：CuRobo cspace 声明
  `max_acceleration: 15.0`、`max_jerk: 500.0`；
- `envs/robot/planner.py`：CuRobo interpolation 使用 `1/250 s`；
- `envs/_base_task.py`：SAPIEN scene timestep 默认为 `1/250 s`；
- `envs/robot/robot.py`：`set_arm_joints()` 写入 position drive target 和
  velocity drive target；初始化 drive property 时只传 stiffness/damping，未证明
  URDF effort 已投影为 SAPIEN force limit。

这些事实给出三个明确边界：

1. URDF joint limits 可以作为 robot-description source 投影给 planner，但必须逐关节；
2. CuRobo acceleration/jerk 是 planner profile 约束，不能自动称为 SAPIEN controller
   的硬约束；
3. 当前 SAPIEN drive-target backend 没有证据证明硬笛卡尔速度限制。

### 3.1 RoboTwin 正确实现路线

RoboTwin adapter 应从选中的 embodiment profile 解析并物化：

- joint name/order；
- position lower/upper；
- velocity lower/upper（逐关节）；
- acceleration/jerk 及其 CuRobo profile 来源；
- effort/force limit 及是否实际绑定到 SAPIEN drive；
- planner interpolation dt 与 simulator dt；
- controller mode、SAPIEN version、robot description digest。

planner 必须使用同一份能力快照完成约束和 provider-native retiming。simulation
worker 在执行前校验 planner output 的 joint order、timestamps、`q/dq/ddq` 有限性和
能力版本；执行后记录实际 `q/dq`、TCP pose/derived velocity、contacts、deadline 和
stop/reset 状态。TCP derived velocity 的语义固定为 `measured_diagnostic`，除非未来
SAPIEN controller adapter 提供并通过验证的 enforcement API。

若要声称 simulator controller 硬限制，必须先完成独立 qualification：对 controller
identity/version、SAPIEN version、timestep、drive parameters、force limits、命令族和
测试覆盖范围做绑定，并验证超限命令、丢步、接触、负载和 reset 路径。仅有 nominal
trajectory 或 observed maximum 不足以证明硬限制。

## 4. Franka 硬件 SDK 的实际链路

硬件路径与 RoboTwin 仿真是两个 provider，不共享底层 controller 结论。

libfranka 官方 `Robot::control` API 的 `limit_rate` 参数默认是 `false`；硬件 adapter
不能假设 rate limiting 已开启，必须显式配置并保存实际 mode。libfranka 还提供
`getUpperJointVelocityLimits()` 与 `getLowerJointVelocityLimits()`，用于获取给定关节
位置下的动态 joint velocity 边界。官方 rate-limiting 接口同时覆盖 joint velocity、
Cartesian translational/rotational velocity、acceleration 和 jerk。官方源码中的
Cartesian maximum（例如 translational velocity 约 `3.0 m/s`）也证明 `0.20 m/s`
不是 Franka 的通用硬件常量。

frankx 提供 `velocity_rel`、`acceleration_rel`、`jerk_rel` 和
`set_dynamic_rel()`。这些是相对运动策略，适合表达任务级降速，但不能仅凭
`dynamic_rel` 宣称 libfranka 的 rate limiter 已启用。硬件 adapter 必须核对实际
frankx/libfranka 调用路径和版本，并证明 `Robot::control(..., limit_rate=true, ...)`
或等效 controller enforcement 确实生效。

官方参考：

- libfranka `robot.h`：<https://github.com/frankarobotics/libfranka/blob/main/include/franka/robot.h>
- libfranka rate limiting：<https://github.com/frankarobotics/libfranka/blob/main/include/franka/rate_limiting.h>
- frankx robot API：<https://github.com/pantor/frankx/blob/master/include/frankx/robot.hpp>

### 4.1 硬件 adapter 必须保存的资格事实

- robot serial/model、firmware、FCI/libfranka/controller version；
- control interface（joint position/velocity、Cartesian pose/velocity、torque）；
- `limit_rate` 的实际值和可复现读取/构造路径；
- 位置相关的 joint lower/upper velocity limits；
- Cartesian translation/rotation、acceleration、jerk limits；
- task policy 的 relative speed 与硬限制的关系；
- controller error/reflex/stop outcome；
- qualification artifact、review state 和适用的软件/硬件 identity 范围。

缺一项时应标为 `unknown` 或 `planner_constrained`，不能标为
`controller_enforced`。

## 5. PAOS 协议与所有权

### 5.1 推荐 MotionCapability artifact

现有 `ArmCapability.motion_capabilities_ref` 保持为不透明 artifact reference。
artifact 由 adapter 生成、由 PlanRevision 冻结，采用逐关节结构：

```yaml
schema_version: paos-motion-capability/v2
robot_identity: franka-panda
arm_id: right
runtime_kind: simulation          # simulation | hardware
provider:
  controller_id: robotwin-sapien-drive-target
  controller_version: <resolved-version>
  planner_id: curobo
  planner_version: <resolved-version>
  robot_description_ref: artifact://.../panda-urdf
joint_order: [panda_joint1, panda_joint2, panda_joint3, panda_joint4,
              panda_joint5, panda_joint6, panda_joint7]
limits:
  position_lower_rad: [...]
  position_upper_rad: [...]
  velocity_lower_radps: [...]
  velocity_upper_radps: [...]
  acceleration_radps2: [...]
  jerk_radps3: [...]
  effort_nm: [...]
  sources:
    position_velocity_effort: artifact://.../panda-urdf
    acceleration_jerk: artifact://.../curobo-profile
enforcement:
  joint_velocity: planner_constrained
  cartesian_velocity: unknown
  joint_effort: unknown
timing:
  planner_dt_s: <provider-derived>
  controller_dt_s: <provider-derived>
  simulator_default_dt_s: <provider-derived-default>
controller_qualification_ref: null
motion_authorized: false
```

这里的数组值只能由 adapter 从选中 provider 实例导出；示例不填具体数字，避免
文档成为第二份配置源。

### 5.2 四类语义必须分开

| 语义 | 含义 | 可用于什么 |
|---|---|---|
| `controller_enforced` | provider/controller 在执行面强制约束，且 identity-matched qualification 通过 | Action admission 的必要物理保证 |
| `planner_constrained` | planner 按能力规划/retime，但 controller 未证明硬强制 | readiness 和轨迹检查，不单独授权动作 |
| `benchmark_policy` | benchmark 为可比性规定的运行速度策略 | 实验配置与评分，不冒充硬件安全限制 |
| `measured_diagnostic` | 从状态差分得到的观测值或阈值 | evidence、故障诊断、回归比较 |

### 5.3 分层所有权

- **Benchmark/robot adapter**：发现 SDK/URDF/controller、生成 capability artifact、
  做 frame/joint-order 映射；
- **Planner/readiness provider**：消费冻结能力，生成带 timestamps 的受约束轨迹并
  返回可行性；
- **Gateway/Action admission**：校验 task/revision/route/capability/qualification
  identity，调用已绑定的 controller adapter；
- **Controller/SDK**：执行并承担硬限制、reflex 和 stop；
- **Evidence/Verifier**：保存 commanded 与 observed state，判定事实和语义结果；
- **Agent/planning/Skill**：选择 arm、tool、顺序和任务级相对速度 policy，不得写入
  或放宽 provider safety limits；
- **Experience/evolution**：可以学习 tool 顺序、候选选择和允许范围内的 task speed
  preference，不能进化 URDF/SDK/controller limit 或伪造 qualification。

## 6. 更换机械臂和 benchmark 的扩展原则

更换 embodiment 时，PAOS 的 task/DAG/tool/Gateway/verifier 协议不应跟着重写。
adapter 解析 benchmark 指定的机器人，生成新的：

```text
EmbodimentBinding
  ├── ArmCapability
  ├── MotionCapability artifact
  ├── PlannerProfile artifact
  ├── Frame/Calibration artifact
  └── ControllerQualification artifact (when available)
```

相同 skill 通过 capability requirements 选择兼容本体。若某 benchmark 规定额外速度
策略，它以 `benchmark_policy` 覆盖在 provider hard limits 之内；它不能替换或提高
provider limits。这样 RoboTwin Franka、其他 RoboTwin embodiment 和真实 Franka
只替换 adapter/profile/artifact，不污染 PAOS Core。

## 7. 迁移与实施顺序

### 7.1 RoboTwin MotionCapability v2 已实现的边界

RoboTwin adapter 现在提供 `paos-robotwin20-motion-capability/v2`。它从选定
checkout 的 `panda.urdf`、embodiment `config.yml`、CuRobo `curobo.yml`、
planner、simulator 和 drive-target source，以及指定的 RoboTwin runtime
interpreter 重新导出并绑定：七个关节的 position/velocity/effort、CuRobo
acceleration/jerk、planner 时间步、simulator 默认时间步、joint order、provider 版本和
每个 source 的 SHA-256。左右臂分别生成 artifact；canonical digest 绑定到
route-request/v5 和 route-source-manifest/v3。

独立验证脚本只产生
`paos-robotwin20-motion-capability-validation/v1` 的
`validated_planner_constraints` 记录。它会重新计算 provider source 和
runtime identity，拒绝 source tamper、joint-order/timing 歧义和 force-limit
越权，并固定 `independent_execution_qualification=false`、
`controller_enforced=false`、`motion_authorized=false`。因此该 artifact
证明“来源和 planner 约束已验证”，不证明 SAPIEN drive-target 在执行时硬性
限制速度。

simulation probe 在读取并校验两臂 artifact、validation digest、robot identity
和 arm coverage 后，仍在 world change 之前拒绝：当前没有独立 controller
qualification。未来真实 controller 只能通过新的 provider-specific artifact
和独立资格证据打开这一门禁，不能修改 v2 validation 的 false 字段或复用旧
approval。

### 阶段 A：本次完成的撤销

- route v4 pose 不再携带无来源的 linear/joint speed 数字；
- route-input profile v3 不再携带 `0.20`、统一 `1.0`、execution scale 或自制 retiming；
- simulation worker 不再缩放 velocity target，也不再以 `0.20` 观测值终止；
- 删除没有真实 provider enforcement 的 `SpeedBoundedExecutionController`；
- 仍记录 finite TCP derived speed、真实执行步、contact、stop 和 reset evidence；
- 历史 v3 route/probe 只读保留。

### 阶段 B：RoboTwin provider-owned capability（本次完成）

1. 从选中的 URDF/CuRobo/profile/runtime 导出 v2 artifact；
2. 逐关节校验 joint order 与 limits；
3. 导出 CuRobo planner timing 和 SAPIEN timestep；controller period 无来源时保持 null；
4. 明确 SAPIEN effort/force-limit wiring；没有 wiring 就标 `unknown`；
5. 完成独立 no-motion source validation；simulation/controller qualification 仍保持分离且未完成。

### 阶段 C：真实 Franka provider（独立环境）

1. 在 hardware-specific adapter 环境安装并锁定 libfranka/frankx；
2. 显式验证 control interface 和 `limit_rate`；
3. 读取动态 joint velocity bounds，物化 hardware capability；
4. 先 dry-run/no-motion，再进行人工批准的 qualification；
5. qualification 未完成前，PAOS Action admission 保持 fail-closed。

## 8. 五个维度审查

### 架构集成

通过。速度真值留在 provider adapter/controller，PAOS Core 只保存引用；没有新建第二套
controller、scheduler 或 lifecycle。

### 失败路径

必须拒绝 missing source、joint-order drift、provider/version drift、timing mismatch、
unsupported control mode、qualification mismatch、NaN/Inf trajectory 和 stale revision。
measurement 失败标记 evidence 不完整，不能转换成硬限制通过。

### 权威边界

通过。Agent 和 Experience 不能修改安全限制；planner 不能宣称 controller enforcement；
simulation qualification 不能授权 hardware；Gateway 仍是唯一执行入口。

### 配置与 provenance

通过。没有 PAOS 全局速度常量；所有数字必须位于 adapter 物化的不可变 artifact 中，
并绑定来源、版本、单位、joint order、enforcement 和 qualification。

### 可维护性

通过。通用协议保持 provider-neutral；RoboTwin 与 Franka SDK 细节分别留在各自 adapter。
诊断 measurement 与 admission contract 分离，可独立测试，不再通过调参修补错误抽象。

## 9. 验收条件

只有同时满足以下条件，某一速度约束才能进入 Action admission：

1. 来源可追溯且与实际 robot/controller/planner identity 一致；
2. 单位、joint order、timing 和 control interface 明确；
3. planner trajectory 使用同一能力快照；
4. controller enforcement 语义由 provider API 和 qualification 证明；
5. command/observed/controller-status evidence 完整；
6. qualification scope 覆盖当前 runtime、负载、命令族和 stop/error 路径；
7. PlanRevision 冻结所有 artifact digest；
8. 人工审核通过，且仅授权声明的 simulation 或 hardware scope。

在这些条件之前，系统可以进行 no-motion planning、诊断和 evidence 收集，但不能把
经验阈值、一次实测最大值或相对速度比例称为真正的硬速度限制。

## 10. Controller qualification execution status (2026-09-06)

The first no-motion milestone is specified in
`ROBOTWIN_CONTROLLER_QUALIFICATION_EXECUTION_PLAN.md`. It now provides
provider-owned plan, source manifest, review request, cross-artifact verifier,
and scoped approval contracts. The real RoboTwin v2 capability package has
been validated without loading a scene. This does not qualify the SAPIEN
drive-target controller: qualification motion, benchmark motion, Gateway,
Dora, Action, and hardware remain disabled until a human approves the new
plan/validation package and an independent worker produces execution evidence.

大步 B 的隔离 qualification worker 已实现于 RoboTwin adapter，记录每个测试的
commanded/observed joint state、TCP pose/velocity、contacts、simulator step/time、
controller status 及 stop/error/reset 信号。原生 drive-target 运行产生了
`unavailable`/`validated_failure` 负证据；新增 bounded controller 后，q3 隔离运行
产生 `passed`/`validated_pass`。这两类结果都不产生 PAOS motion authorization。

基于该负证据，RoboTwin adapter 新增 capability-driven provider controller。它在
SAPIEN drive-target 写入之前执行逐关节 limits、命令长度、finite value、stop/fault
和 step acknowledgement 检查；限制数值仍只来自 MotionCapability artifact，不在
PAOS Core 或代码中硬编码。由于 controller source/identity 变化，必须重新生成
capability、qualification plan 和人工 approval，旧 approval 不得复用。

q3 通过仅限于其 controller source digest 和双臂 SAPIEN qualification scope。单臂
调度语义修正后已生成 q4 新 plan，必须重新进行 plan approval 和 qualification；在
q4 已完成隔离 controller qualification 并通过独立 evidence validation。它证明的是
当前 bounded provider controller 对逐关节 limits、越限拒绝、stop/error/reset、
dropped-step、contact fixture 以及单臂/双臂 step 语义的执行资格。它仍不代表真实
Franka SDK 的 hardware qualification，也不会自动改变 PAOS Gateway 或 route admission；
最终结果必须经过独立人工审批后才能进入下一阶段。
