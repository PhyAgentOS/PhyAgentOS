# PhyAgentOS Documentation

版本 / Version: **0.1.4.post4**<br>
实现基线 / Implementation baseline: **Forge-only source, 2026-08-03**

本目录由 PhyAgentOS 开发团队面向用户、运维人员和生态开发者维护。文档只把仓库源码、配置 Schema 与测试实际覆盖的行为称为“当前能力”。`plan/` 中的设计报告是历史背景，不替代这里的运行契约。

The PhyAgentOS team maintains this directory for users, operators, and ecosystem developers. A feature is described as current only when it is supported by repository source, configuration schemas, and tests. Historical reports under `plan/` provide design context but do not replace the operational contract documented here.

## 中文

### 核心手册

1. [框架介绍](zh/01-framework-introduction.md)：项目定位、控制面边界、执行—证据—判定分离、生命周期与实现范围。
2. [用户手册](zh/02-user-manual.md)：安装、Provider/Forge 配置、任务描述、验证模式、Artifact 与排障。
3. [开发者手册](zh/03-developer-manual.md)：公共模型、状态机、Gateway 身份校验、Evidence、Verifier、Recovery 与测试。
4. [Forge 配置参考](zh/04-forge-configuration-reference.md)：全局 Forge、Evidence、Verification、Task Contract 和 Embodiment 字段。

### 专题手册

- [运行手册](user_manual/README.md)：上线前检查、启动顺序、状态观测、取消、重启恢复、备份与故障分层。
- [集成开发指南](user_development_guide/README.md)：为 Gateway 增加 action、提供证据源、对接 Provider，以及 PAOS 扩展边界。
- [通信架构](user_development_guide/COMMUNICATION.md)：Agent 消息、Forge HTTP/WebSocket、system event、SQLite 与 Artifact 边界。
- [Forge 接入契约](forge/README_zh.md)：Gateway 1.0.0 的完整执行、证据、验证、恢复和崩溃恢复契约。

### 推荐阅读路径

| 目标 | 建议路径 |
|:-----|:---------|
| 先理解项目为何区分执行与任务成功 | [框架介绍](zh/01-framework-introduction.md) → [Forge 接入契约](forge/README_zh.md) |
| 首次部署并跑通 Agent + Forge | [用户手册](zh/02-user-manual.md) → [配置参考](zh/04-forge-configuration-reference.md) |
| 负责长期在线和故障处理 | [运行手册](user_manual/README.md) → [通信架构](user_development_guide/COMMUNICATION.md) |
| 在 Gateway 增加新机器人动作 | [集成开发指南](user_development_guide/README.md) → [开发者手册](zh/03-developer-manual.md) |
| 修改证据、验证、恢复或持久化 | [开发者手册](zh/03-developer-manual.md) → [Forge 接入契约](forge/README_zh.md) |

## English

### Core manuals

1. [Framework Introduction](en/01-framework-introduction.md): positioning, control-plane boundaries, execution/evidence/verdict separation, lifecycle, and implemented scope.
2. [User Manual](en/02-user-manual.md): installation, provider and Forge configuration, task description, verification modes, artifacts, and troubleshooting.
3. [Developer Manual](en/03-developer-manual.md): public models, state machine, Gateway identity validation, evidence, verifier, recovery, and testing.
4. [Forge Configuration Reference](en/04-forge-configuration-reference.md): exact global Forge, evidence, verification, task-contract, and embodiment fields.

### Focused manuals

- [Operations Manual](user_manual/README_en.md): preflight checklist, startup order, observation, cancellation, restart recovery, backup, and failure layers.
- [Integration Development Guide](user_development_guide/README_en.md): adding Gateway actions, exposing evidence sources, connecting providers, and PAOS extension boundaries.
- [Communication Architecture](user_development_guide/COMMUNICATION_en.md): Agent messages, Forge HTTP/WebSocket, system events, SQLite, and artifact boundaries.
- [Forge Integration Contract](forge/README.md): the complete Gateway 1.0.0 execution, evidence, verification, recovery, and crash-recovery contract.

### Suggested reading paths

| Goal | Suggested path |
|:-----|:---------------|
| Understand why execution and task success differ | [Framework Introduction](en/01-framework-introduction.md) → [Forge Integration Contract](forge/README.md) |
| Deploy Agent + Forge for the first time | [User Manual](en/02-user-manual.md) → [Configuration Reference](en/04-forge-configuration-reference.md) |
| Operate a long-running service | [Operations Manual](user_manual/README_en.md) → [Communication Architecture](user_development_guide/COMMUNICATION_en.md) |
| Add a new robot action in Gateway | [Integration Guide](user_development_guide/README_en.md) → [Developer Manual](en/03-developer-manual.md) |
| Change evidence, verification, recovery, or persistence | [Developer Manual](en/03-developer-manual.md) → [Forge Integration Contract](forge/README.md) |

## Terminology

| Term | Meaning |
|:-----|:--------|
| PAOS session | The persistent orchestration record owned by PhyAgentOS. Its ID is also sent to Gateway as the requested session ID. |
| Gateway command | The high-level Forge action identified by a PAOS-generated command ID. |
| Execution Record | Immutable normalized facts derived from the Gateway session and command. |
| Evidence Bundle | Validated, workspace-relative artifact references and capture-quality metadata. |
| Verdict | A structured semantic decision over every success criterion. |
| Root lineage | The original task plus any Planner-created recovery children. It owns the single execution slot. |

## Compatibility note

Active documentation intentionally contains no compatibility instructions for the removed PAOS Runtime/Target/SkillRuntime/Watchdog/SessionRunner/Markdown queue architecture. Existing user workspaces are not deleted automatically; see the cleanup section in the [User Manual](en/02-user-manual.md#13-legacy-workspace-cleanup) or [用户手册](zh/02-user-manual.md#13-旧工作区清理).
