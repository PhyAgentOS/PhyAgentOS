# PhyAgentOS 集成开发指南

> 版本：v0.1.6 · [English](README_en.md)

本指南由 PhyAgentOS 开发团队面向生态集成开发者编写，说明如何把新的 Target、Policy 或执行能力接入当前 Session-Centered Runtime。

## 1. 选择正确扩展点

| 需求 | 扩展点 | 不应修改 |
|---|---|---|
| 新执行环境/机器人 | `BaseRolloutTarget` + TargetAdapter + Contract | AgentLoop、Scheduler |
| 新策略服务 | `BasePolicyClient` + PolicyAdapter | Target 内部实现 |
| 新闭环执行方式 | Policy/Builtin SkillRuntime | 原始 Target/SDK |
| 新动作转换 | `BaseActionBridge` | Adapter 中的隐式裁剪 |
| 新感知模型 | Perception Plugin + Config | `ENVIRONMENT.md` 手工写入 |
| 新消息入口 | Channel | Runtime Session 状态机 |

## 2. Target 接入闭环

1. 定义 Target 的生命周期、Observation、Action 和 Tool Contract。
2. 实现 `BaseRolloutTarget`；Remote Target 使用 `TargetWSClient`/`RemoteTargetProxy`。
3. 实现 TargetAdapter，并让其输入输出 Contract 可被 Preflight 比较。
4. 编写 `runtime_target_contract_v1` YAML。
5. 注册 Runtime Factory。
6. 在 `TARGETS.md` 声明 Target，只关联已验证 Skill Runtime。
7. 编写拒绝路径、成功路径、超时、取消和资源释放测试。

Local 注册：

```python
register_local_target_runtime("MyTargetRuntime", build_my_target)
```

Remote 注册：

```python
register_remote_target_runtime("MyRemoteTargetProxy", build_my_proxy)
```

v0.1.6 使用显式 Python 注册，不使用旧 Driver 插件清单。

## 3. Skill Runtime 接入闭环

Policy 型：

```text
Target.observe
→ TargetAdapter.to_runtime_observation
→ PolicyAdapter.to_policy_input
→ PolicyClient.infer
→ PolicyAdapter.from_policy_output
→ ActionBridge
→ TargetAdapter.to_executable_action_chunk
→ Target.action_chunk
```

Builtin 型：

```text
BuiltinSkillRuntime
→ TargetSessionHandle.call_target_tool
→ TargetToolManifest validation
→ Target.call_target_tool
```

Skill Runtime 不能获得原始 Target，也不能自行连接 TargetWS。

## 4. Contract 设计

### Observation

- TargetAdapter 的输出必须覆盖 PolicyAdapter 的必需 Sensor Key。
- Shape、dtype、layout 必须显式兼容。
- Empty Observation 需要 Target 和 Skill 双方声明；Policy Runtime 当前拒绝 Empty Observation。

### Action

- `representation` 必须在 Target accepted representations 中。
- 二维 Action Shape 的最后一维必须一致。
- normalized → non-normalized 需要显式 denormalization Bridge。
- 不允许隐式截断、补零或 representation cast。

### Perception

- Sensor Config 描述采集与 Observation Schema。
- Perception Config 描述 Model、Plugin 和 Pipeline。
- Skill `requires` 描述本次执行真正需要的输出。

## 5. Remote Target 协议

使用 `phyagentos.runtime_rpc.v2` + msgpack。请求和响应至少保持：

```yaml
version: phyagentos.runtime_rpc.v2
type: target.observe
session_id: sess_001
target_id: target_001
skillruntime_id: skill_001
seq: 1
timestamp_ns: 0
trace_id: trace_001
payload: {}
```

Response 必须匹配 type（`target.observe` 对应 `target.observation`）、seq、session、target 和 skillruntime。错误返回 `runtime.error`，包含稳定 error code 与可操作 message。

完整职责见[通信架构](COMMUNICATION.md)。

## 6. 开发调试流程

```bash
# 1. 初始化隔离工作区
python scripts/init_runtime_workspace.py --workspace /tmp/my-runtime

# 2. 编辑 TARGETS/SKILLRUNTIME/Contract/SESSIONS

# 3. 单 Session 执行
python scripts/run_runtime_watchdog.py \
  --workspace /tmp/my-runtime --once --session-id <id>

# 4. 核心测试
pytest tests/runtime
```

优先验证错误路径：未知 Runtime、错误 Endpoint、缺失 Adapter、Shape 不兼容、Sensor 缺失、Target timeout。一个集成只有在拒绝路径也确定时才具备可运维性。

## 7. Artifact 与状态写回

- Session 状态只由 `SessionRegistry` 推进。
- `ResultWriter` 写 `LOG.md`、Episode 和 LESSONS。
- `EnvironmentWriter` 负责 Environment v2 reconcile/merge。
- 大型数组、图像和点云写 Artifact，不写 Markdown。
- 模型语义验收与严格响应规范化由 Agent 管理的 Verification Service 完成；
  `SessionVerifier` 应用 policy-loop verdict，target-native benchmark 则在
  attempt 边界向同一服务请求 episode verdict。

## 8. 真机接入要求

当前 `preview` Runtime 已注册受约束的 `go2_real_builtin` real-robot Target。
其他真机生态集成仍必须在 Target 侧实现安全边界，至少包括急停、范围/速度/力
限制、命令时效、Operator Override、断连停止和幂等 cancel/close。现有
Preflight 通过不代表完成真机安全认证。

## 9. 合入门禁

提交新 Runtime 集成时应提供：

- Target/Skill/Adapter/Contract 的完整注册关系
- 可复现的 Dummy 或 Mock 测试
- Preflight accepted 与 rejected 用例
- Timeout/Cancel/Close 资源释放用例
- 一个端到端 Session Artifact
- 中英文用户启动说明和已知边界

## 10. 后续设计方向

HAL v3 规划继续完善 strict Environment Contract、real-robot SafetyGuard、依赖调度、Agent-interactive Runtime、Goal Graph/Session Compiler 和 Fleet 编排。扩展实现应沿这些边界演进，不重新引入 Driver-Centered 跨层调用。

## 相关文档

- [Unitree Go2 快速接入手册](UNITREE_GO2_QUICK_START.md)
- [开发者手册](../zh/03-developer-manual.md)
- [通信架构](COMMUNICATION.md)
- [运行手册](../user_manual/README.md)
