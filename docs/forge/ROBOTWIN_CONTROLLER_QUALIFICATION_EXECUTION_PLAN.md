# RoboTwin/SAPIEN Controller Qualification 执行计划

状态：执行中（2026-09-06）  
适用范围：RoboTwin 2.0、双 Franka-Panda、SAPIEN drive-target backend  
首个目标任务：`blocks_ranking_rgb`  

## 1. 目标与非目标

目标是在不改变 PAOS 权威边界的前提下，取得或否定一份与当前 RoboTwin checkout、
runtime、SAPIEN controller、命令族和左右臂 capability 严格绑定的独立执行资格证据。
资格测试允许得出 `failed` 或 `unavailable`；生成 artifact 不等于测试通过。

本阶段不把 planner limits、URDF 数值、一次观测最大值或人工审批解释为 controller
enforcement，也不授权 `blocks_ranking_rgb`、Gateway、Dora、Action 或硬件执行。

## 2. PAOS 所有权边界

```text
RoboTwin adapter
  qualification plan / provider worker / evidence / result
                 │ immutable refs + digests
                 ▼
PAOS PlanRevision / route admission
  freeze and validate bindings; never manufacture controller facts
                 │ approved simulation-only authorization
                 ▼
Gateway / Action admission
  remains the only production execution authority
```

- qualification 协议和 worker 属于 RoboTwin adapter；
- MotionCapability 继续描述 provider 能力来源，不因 qualification 计划被原地改写；
- qualification result 是独立 artifact，不创建第二套 AgentTask、SQLite 或 scheduler；
- Planning/Skill/Experience 可以读取结论，但不能写入或放宽 controller limits；
- Verifier 保存执行事实和语义判定，不能反向授权动作。

## 3. 大步与门禁

### 大步 A：协议、无动作预检和审核包

1. 定义严格、不可变的 `ControllerQualification` 协议；
2. 绑定 robot/arm、RoboTwin revision、runtime、SAPIEN/controller identity；
3. 绑定左右臂 MotionCapability artifact、validation 和 source manifest digest；
4. 固定命令族和测试矩阵：nominal、over-limit、contact/load、dropped-step、stop、
   error、reset；
5. 实现只读 validator 和 no-motion dry-run；
6. 生成新的、不可覆盖的人工审核包。

完成条件：协议测试和全量回归通过；dry-run 明确
`world_change_started=false`、`motion_authorized=false`；五维审查无 Blocker/Major。

### 大步 B：人工批准后的隔离 qualification motion

只有审核者明确批准大步 A 生成的 request/source-manifest digest 后才可执行。审批仅适用
于 isolation scene 的资格测试，不能用于 benchmark 或硬件。

worker 必须：

- 在任何 `scene.step()` 前重新验证审批、capability、runtime 和 controller identity；
- 从 provider capability 读取逐关节限制，不使用 PAOS 全局常量或经验 `0.20 m/s`；
- 保存 commanded/observed `q`、`dq`、TCP pose/derived velocity、contacts、step/time、
  controller status、stop/error/reset；
- 每次 `scene.step()` 后立即更新 world-change 计数；
- stop、timeout、NaN/Inf、identity drift、artifact drift 或证据写入失败时 fail-closed；
- 无论成功或失败都 reset/close scene，并明确 reconciliation 状态。

完成条件：得到真实 `passed`、`failed` 或 `unavailable` evidence；独立 validator 重放
全部证据；人工只可批准 evidence 结论，不能修改测试结果。

### 大步 C：route 重新绑定和单对象 smoke test

仅当 qualification 为 `passed`、独立验证通过且人工审核为 `approved` 时执行：

1. 生成新 MotionCapability/qualification binding 和新 route/source manifest；
2. 重新进行 route simulation-only 人工审批，旧 route/approval 不复用；
3. 执行 `blocks_ranking_rgb` 单对象 pick-place；
4. 保存 lift、attached-object collision、transport、descent、release、retreat、contact、
   before/after snapshot 和 after-semantic evidence；
5. 任何结果未知都进入 reconciliation，不自动重试动作。

### 大步 D：完整长程 benchmark

单对象 smoke test 和语义验收通过后，才由 Agent 生成三个 relocate 子任务及其任务级
DAG，动态选择 arm/candidate/tool。每个动作节点仍通过同一 admission、Gateway、
evidence 和 verifier，不把 Skill workflow 写成固定执行脚本。

## 4. 五维验收模板

每个大步完成后都记录：

1. **架构集成**：实现只落在 owner 层；无第二生命周期、执行面或事实源；
2. **失败路径**：missing/stale/tampered/unknown/timeout/stop/reset/reconciliation 均有测试；
3. **权威边界**：qualification 不等于 motion authorization，Gateway/Verifier 职责不变；
4. **配置与 provenance**：无硬编码机器人限制；identity、版本、digest、单位和 command
   family 全部冻结；
5. **可维护性**：provider contract、worker、validator、CLI 和测试分离，可替换 embodiment
   而不修改 PAOS Core。

发现 Blocker/Major 时必须先修复并重跑该大步验收；不得以增加审批字段、降低阈值或
重复调参绕过失败。

## 5. 当前状态与下一动作

- MotionCapability v2/source validation/route v5：已完成；
- controller qualification：大步 A 已完成；大步 B worker/validator 已实现；
- qualification motion：旧 q2 plan 已获得隔离 simulation-only 审批，运行结果为 failed/unavailable；新 bounded-controller q3 plan 尚未审批；
- benchmark motion：未授权、未执行；
- Gateway/Dora/Action/hardware：未接入本阶段。

当前大步 A 已完成，并已获得审核者对旧 q2 包的显式
`I_REVIEWED_AND_APPROVE_CONTROLLER_QUALIFICATION_SIMULATION_ONLY` 批准。大步 B 的
worker、独立 evidence validator 和失败产物已实现；旧 q2 运行已加载 SAPIEN，但暴露
原生 drive-target 没有越限拒绝、contact-load、dropped-step 和 error-path 资格能力。
该负证据不能升级为 controller qualification，也不能启动 benchmark 或 route motion。

当前已根据该负证据新增 provider-owned
`paos-robotwin-capability-bounded-drive-target` controller。它不修改 SAPIEN 或 URDF
物理事实，而是在 provider command boundary 使用绑定的 MotionCapability 逐命令检查
joint order、position/velocity limits、finite values、stop/fault 状态和 simulator-step
acknowledgement；越限和非法命令在到达 SAPIEN 前拒绝。该 controller 的源码摘要已纳入
新的 MotionCapability artifact，因此旧 `robotwin-sapien-drive-target` approval 不能复用。

## 6. 大步 B 实现与实际结果（2026-09-06）

新增 `runtime/robotwin_controller_qualification_worker.py`，其边界为：

- `QualificationRuntime` 是 provider port；worker 不导入 PAOS lifecycle、Gateway、Dora 或 Action；
- `SapienQualificationRuntime` 只创建空的双 Panda 场景，不加载 benchmark task objects；
- 每次 `scene.step()` 前检查 stop file、超时、approval scope 和所有输入 artifact digest；
- 命令来自 capability 的逐关节 velocity/position limits，代码不加入 PAOS 全局速度常量；
- trace 保存 commanded/observed q、dq、TCP pose、derived TCP velocity、contacts、step/time、
  controller status 和 stop/error/reset 状态；NaN/Inf、artifact drift、stop 和 provider fixture
  缺失均 fail-closed；
- `over_limit_velocity_command` 只有在 provider 明确返回 `rejected`、`limited` 或 `fault`
  时才可能通过；仅观察到低速不构成 controller enforcement 证据；
- worker 无法创建 SAPIEN 时，CLI 生成完整的 `unavailable` evidence 和每个测试的 failure
  trace，而不是只打印错误或伪造 pass；
- `validate_controller_qualification_evidence.py` 独立检查 plan/approval digest、全部 trace
  digest、双臂信号、有限值和失败原因，并输出 `validated_failure`/`validated_pass`；输出仍
  固定 `motion_authorized=false`。

旧 q2 实际运行：

```text
status=unavailable
reason=over-limit controller rejection and contact/error/drop fixtures unavailable
evidence=/home/yanxu/robotwin20-runtime/artifacts/qualification-run-20260906T1630Z-v6/controller-qualification/blocks-ranking-rgb-franka-sapien-q2/evidence.json
validation_status=validated_failure
motion_authorized=false
```

因此目前的真实结论是：worker 和证据协议可运行，SAPIEN scene 可加载，但原生
drive-target controller qualification 未通过。新的 capability-bounded controller
已生成 q3 plan；在新人工审批前不得执行 q3 qualification motion。

### 大步 B 五维验收

- **架构集成：通过。** worker/validator 留在 RoboTwin adapter；`QualificationRuntime` 是
  可替换 provider port，不创建第二套 PAOS task、SQLite 或执行事实源。
- **失败路径：通过。** 覆盖 package digest drift、stop/timeout、NaN/Inf、缺失 fixture、
  over-limit 未被 controller 拒绝、缺失 trace、trace digest drift 和 provider unavailable；
  失败结果持久化为 `failed` 或 `unavailable`，不伪造成功。
- **权威边界：通过。** qualification approval 仅允许隔离测试；证据和独立 validation
  始终 `motion_authorized=false`，不能授权 benchmark、Gateway、Dora、Action 或硬件。
- **配置与 provenance：通过。** 计划、审批、capability、validation 和 source manifest
  的 digest 在启动及每步前检查；限制来自 provider-owned MotionCapability，未新增硬编码
  `0.20` 等速度值。
- **可维护性：通过。** contract/worker/provider/CLI/validator/测试分层；SAPIEN 缺失时
  有可审计 unavailable artifact，便于在独立 provider 环境重放。

专项测试：`15 passed`（qualification contract + worker）；Ruff、compileall 通过。

## 7. 下一步门禁

1. 在独立 RoboTwin20 provider 环境安装并锁定 SAPIEN、PyYAML、NumPy 和 RoboTwin checkout，
   记录 runtime/controller identity；
2. 用新的唯一 artifact root 重跑 `run_controller_qualification.py`（同一 plan 仅在所有
   digest 未变时可复用批准）；
3. 对生成的 evidence 运行独立 validator，并人工审核 `validated_pass` 或 `validated_failure`；
4. 只有 `validated_pass` + 新人工批准，才进入大步 C 的 route 重绑定；当前不能运行
   `blocks_ranking_rgb`、pick-place、Gateway、Dora、Action 或硬件。

## 8. Capability-bounded controller milestone（2026-09-06）

新 controller 合约位于 `runtime/robotwin_capability_controller.py`，通过
`CapabilityBoundedDriveController` 提供：

- 每个命令的 joint-order、position、velocity、长度和 finite-value 检查；
- accepted → running → ready 的 step acknowledgement；未结算、丢失 step、stop 和
  fault 状态均阻断后续命令；
- provider write failure 进入 fault，reset 只能回到 ready；
- 计数器记录 accepted/rejected/settled steps，便于 qualification trace 审计。

本阶段为该 controller 生成了新的 capability 和 plan：

```text
capability_root=/home/yanxu/robotwin20-runtime/artifacts/paos-capability-bounded-controller-20260906T1830Z/
left_capability_sha256=57f0d3c5ee8514e20d23eb7ccdee6b8dd9e60403378b88ea38348cf3efad63ca
right_capability_sha256=6971961f348286d09efc84b07dfa3deaac95ee5e6f35d48361d12087e55e538a
plan_root=/home/yanxu/robotwin20-runtime/artifacts/paos-controller-qualification-plan-20260906T1845Z/
plan_sha256=4f0cf0ddf7e20faad11729edd30220e1421689197bf869a0ef0f541ecaca4c9c
source_manifest_sha256=61119a20f0484649989167cc3e59d7a5159897874df8cb3a50941ac367b7239b
no_motion_validation_sha256=ff0d24137973149b610627d167370dad510383acc4270415ef48105e8117fa89
```

该 plan 当前状态为 `pending_human_review`，尚未创建新的 qualification approval。
必须由人工明确审核该新 plan/source-manifest digest 后，才允许执行隔离 qualification；
旧 q2 审批不适用于 q3 controller identity。

### q3 qualification 运行结果（2026-09-06）

q3 plan 获得隔离 simulation-only 审批后，实际运行于空双 Franka SAPIEN 场景：

```text
artifact_root=/home/yanxu/robotwin20-runtime/artifacts/qualification-run-20260906T2015Z/
qualification_status=passed
evidence_sha256=deda609a888526a6c2808f6bc0137407fd3a97f9f5d8f983c21bce8c9e93e4fd
validation_status=validated_pass
validation_sha256=0f4d9dfdb63d362351bb8eb7091eee0d85c950bef12816bb4363fc50613efac3
motion_authorized=false
```

八项测试均产生了 trace：nominal position/velocity、over-limit rejection、contact
fixture、dropped-step、stop、error 和 reset。该结果证明 q3 provider controller 在
当前 SAPIEN runtime 下的隔离 command-admission 和状态路径满足 qualification contract，
但仍不授权 benchmark、route、Gateway、Dora、Action 或硬件。

随后修正了单臂调度语义：空闲 arm 不再被强制要求每个物理 step 都有 pending command，
而是保持当前 drive target；这改变了 controller source digest，因此 q3 evidence 不
能覆盖 q4。已生成新的 q4 capability/plan，必须重新审批。

### q4 plan（单臂调度修正版）

```text
capability_root=/home/yanxu/robotwin20-runtime/artifacts/paos-capability-bounded-controller-20260906T2130Z/
left_capability_sha256=34ebcdd16028c3f62018e7c934a06a725ae23d7478024fb0b551b1aca723e5f5
right_capability_sha256=1828e7d5e4beb075bf64bd879f53198921c78df0475ab53a5140b0a9ddd435d9
plan_root=/home/yanxu/robotwin20-runtime/artifacts/paos-controller-qualification-plan-20260906T2145Z/
plan_sha256=99233d0ce8c885936277894e4265cc255c3ea561bc6edfec91239234e13dea98
source_manifest_sha256=e8d69f9d61b5c8d3d75de226c471322560c39c74898a67641eb54f0f7fca5579
review_request_sha256=92cd83039e41b3e060c24fc2b1dc1a51964e5de372fb1b51c23dd54eae54ca95
no_motion_validation_sha256=5aad1ee2c0d041e39a2d2c6deebcb217ad9fe182ed84c3f4b5b66a70f54729e0
```

q4 当前为 `pending_human_review`，没有执行任何 q4 qualification motion。

### q4 qualification 运行结果（2026-09-06）

q4 在获得新 plan 的隔离 simulation-only approval 后，于全新 artifact root 运行完成：

```text
artifact_root=/home/yanxu/robotwin20-runtime/artifacts/qualification-run-20260906T2245Z/
qualification_status=passed
evidence_sha256=e8fd8a72003f1df9a5dc3418c36f666e1b0e179ec7c17e3601836887e03841f8
validation_status=validated_pass
validation_sha256=da0a02604e59c92a60abf219b1778f70768ec53e052b6b363710671e428bc5aa
motion_authorized=false
```

八项测试全部通过并有独立 trace：nominal position/velocity、over-limit rejection、
contact fixture、dropped-step、stop、error 和 reset。q4 是当前 controller source
digest 和单臂 idle-arm semantics 的有效 qualification；q3 evidence 保留为历史记录，
不覆盖 q4。

### q4 五维验收

- **架构集成：通过。** 单臂 pending-step 语义位于 RoboTwin provider runtime；PAOS task、DAG、Gateway 和 SQLite 所有权不变。
- **失败路径：通过。** q4 实际验证越限拒绝、contact、dropped-step、stop、error、reset 和双臂共享/单臂独立 step；所有失败仍生成可审计 evidence。
- **权威边界：通过。** q4 `validated_pass` 只证明隔离 provider controller qualification，仍固定 `motion_authorized=false`，不授权 benchmark 或硬件。
- **配置与 provenance：通过。** q4 plan、approval、capability、controller source digest、runtime identity 和 trace digest 全部绑定。
- **可维护性：通过。** 结果审批与计划审批分离；最终 `ControllerQualification` 只能通过独立结果审批 CLI 生成。

当前仍缺少最终结果人工确认。必须对 q4 evidence/validation 审核后，才能生成
`ControllerQualification(status=approved_pass)`；在该记录生成前不得进入 route 重绑定。

### q4 最终 qualification（2026-09-06）

q4 evidence/validation 已获得独立结果审批
`I_REVIEWED_AND_APPROVE_CONTROLLER_QUALIFICATION_EVIDENCE`，并生成最终记录：

```text
qualification=/home/yanxu/robotwin20-runtime/artifacts/qualification-run-20260906T2245Z/controller-qualification/blocks-ranking-rgb-franka-bounded-q4/qualification.json
status=approved_pass
qualification_sha256=50ac70982b1dcdeb67ae65cfbd0e3ff3fcc31ebca5b7dd99baa7dcb03f3dc8e6
motion_authorized=false
benchmark_motion_authorized=false
hardware_motion_authorized=false
```

最终 artifact 已通过 `validate_controller_qualification.py --kind qualification`。
该记录只证明当前 RoboTwin bounded provider controller 的隔离 qualification，不是
真实 Franka SDK hardware qualification，也不会自动修改 route/Gateway authorization。

### 大步 B 完成后的门禁

大步 B 现在完成：plan approval、实际 qualification motion、独立 evidence validation
和最终结果人工审批均已具备。下一步进入大步 C 前，仍必须：

1. 用 `approved_pass` qualification 重新生成新的 route/source manifest；
2. 将 q4 qualification digest 绑定到 route admission；
3. 对新 route 进行独立 simulation-only 审批，旧 route approval 不复用；
4. 先执行单对象 smoke test，保存完整 lift/transport/descent/release/retreat/contact
   和 before/after semantic evidence；
5. 单对象语义验收通过后，才能进入 `blocks_ranking_rgb` 长程 DAG。

## 附录 A：大步 A 实际完成记录（2026-09-06）

已完成 provider-owned qualification plan、source manifest、human review request、
cross-artifact verifier 和 approval CLI。真实 v2 capability 输入生成了不可覆盖包：

```text
/home/yanxu/robotwin20-runtime/artifacts/paos-controller-qualification-plan-20260906T1630Z/
plan_sha256: accf3608a18c76f3aa2c044a387e827629f751216499aad2549ba01b65c9281d
source_manifest_sha256: 86433f298c21f1e1bb34c77c7f3c95a3cbf89946192310d134fa5e216b822445
review_request_sha256: 7c0a95a73a92be6c975e054439d7837beb941029fb3e5b61bd7a4c1a64efa19f
no_motion_validation_sha256: 2d977c2ec9ae179fa7ad9ae37b82367e2ddf84b9d3daded96ea2841f69af497e
```

独立 verifier 结果为 `validated_no_motion_plan`，`world_change_started=false`；没有
加载场景、调用 `scene.step()`、Gateway、Dora、Action 或硬件。

### 大步 A 五维验收

- 架构集成：通过。协议和脚本属于 RoboTwin adapter，不创建 PAOS 第二生命周期、数据库或执行平面。
- 失败路径：通过。覆盖缺失/重复测试、错误 digest、provider identity drift、错误审批短语和不完整绑定。
- 权威边界：通过。plan validation、qualification approval 均保持 `motion_authorized=false`；approval 的 `qualification_motion_authorized=true` 只表示隔离资格测试范围，不能授权 benchmark 或 hardware。
- 配置与 provenance：通过。左右臂 capability/validation、source manifest、plan、review request 全部交叉绑定；未写入速度常量或第二份能力事实源。
- 可维护性：通过。contracts、materializer、verifier、approval CLI 和测试分离，未来可替换 provider 而不修改 PAOS Core。

专项测试：`10 passed`；组合回归：`728 passed, 1 skipped`；Ruff、compileall、
`git diff --check` 通过。

结论：大步 A 已完成并通过五维验收。当前仍不能执行大步 B；下一步必须由人工审核
上述新 plan/validation 包后，才允许实现和运行隔离 qualification worker。即使大步 B
通过，也必须重新生成新的 route 并重新审批，不能复用现有 route approval。
