# PAOS Forge Skill 安装与开发

> PhyAgentOS 0.1.4.post4 · Forge ToolEndpoint `forge.tool.endpoint/v1alpha1` · [English](README.md)

本文说明当前已经落地的 PAOS Forge Skill 安装、运行和开发流程。PAOS 负责 Skill
安装与 Dora dataflow 生命周期；Gateway、Forge Runtime、Policy Node 和硬件集成位于
PAOS 外部。

`move-arm-by-ee` 使用 Gateway Tool API 执行 Query 和 Action Tool，不依赖旧的高层
Session 执行面。

## 1. 当前运行链路

```text
Resource Registry
  ├── Skill 名称 -> TOS Bundle URL + SHA-256 + size
  └── Node artifact_id -> GitHub Release URL
             │
             ▼
paos skill install
  ├── 校验并安装 Skill Bundle
  ├── 解析并安装缺失的锁定 Node
  └── 生成 profile 对应的不可变运行环境
             │
             ▼
paos skill start
             │
             ▼
Dora dataflow -> Forge Gateway Tool API -> ToolEndpoint
```

`examples/forge-skills/move-arm-by-ee/` 是参考源码，不会进入 PAOS wheel，也不会因为
拉取 PhyAgentOS 仓库而自动成为已安装 Skill。已安装 Skill 位于
`~/.PhyAgentOS/skills/`。

## 2. Resource Registry

PAOS 默认使用公共开发 Registry：

```text
https://paos-resource-manager.dev.x-era.com
```

默认安装路径不需要额外配置。Registry URL 的生效优先级为：

1. 环境变量 `PAOS_RESOURCE_REGISTRY_URL`；
2. `~/.PhyAgentOS/config.json` 中的 `resourceRegistry.url`；
3. PAOS 内置的公共开发 Registry。

私有部署可以写入：

```json
{
  "resourceRegistry": {
    "url": "https://registry.example.com"
  }
}
```

也可以临时覆盖：

```bash
export PAOS_RESOURCE_REGISTRY_URL=https://registry.example.com
```

Registry 只提供资源目录与下载坐标：

- Skill Bundle 存储在 TOS，Registry 返回 URL、SHA-256 和大小；
- Node `.tar.gz` 存储在 GitHub Release，Registry 根据 `artifact_id` 返回不可变 URL；
- Node 的版本、平台、架构、入口文件和 SHA-256 由 Skill Bundle 内的 lock 固定。

PAOS 不直接读取资源服务仓库中的 `skills.yaml` 或 `nodes.yaml`。

## 3. 安装与运行 Skill

安装已发布的 `move-arm-by-ee`：

```bash
paos skill search move-arm-by-ee
paos skill install move-arm-by-ee
paos skill inspect move-arm-by-ee
```

`install` 会显示 Skill Bundle 来源、大小和后续 Node 下载提示，并要求 `y/N` 确认。
非交互自动化可使用：

```bash
paos skill install move-arm-by-ee --yes
```

下载过程会显示资源名称、URL、已传输字节、总大小、速度、剩余时间、缓存命中和续传
进度。安装失败不会替换原有 Skill。

启动 MuJoCo profile：

```bash
paos skill start move-arm-by-ee --profile mujoco
paos skill status move-arm-by-ee
paos agent -m "将夹爪向前移动 5cm"
paos skill logs move-arm-by-ee --lines 100
paos skill stop move-arm-by-ee
```

Skill 采用显式生命周期：用户先执行 `paos skill start`，确认 Tool ready 后再进入 Agent
对话，使用结束后执行 `paos skill stop`。

## 4. 下载和安装模型

### 4.1 Skill Bundle

Skill Bundle 是平坦的 `.tar.gz`，根目录直接包含：

```text
archive-manifest.json
skill.yaml
SKILL.md
profiles/...
assets/...
```

PAOS 校验 Registry 提供的 Bundle SHA-256 和大小，并逐项校验
`archive-manifest.json` 中声明的文件。归档不得包含包裹层目录、路径逃逸、软链接、
硬链接或特殊文件。

### 4.2 Node lock

每个 Node lock 固定：

```text
artifact_id
version
platform
arch
artifact_type = executable_tar_gz
entrypoint
sha256
```

Node Release 资产是 `.tar.gz`，归档根目录只能包含一个与 `entrypoint` 同名的普通
可执行文件。PAOS 校验 GitHub Asset SHA-256，安全提取文件、设置执行权限并写入安装
回执。

### 4.3 本地目录

```text
~/.PhyAgentOS/
├── skills/<skill-name>/
├── cache/
└── forge_runtime/
    ├── nodes/<node-id>/versions/<artifact-id>/
    │   ├── .paos-node.json
    │   └── <entrypoint>
    └── environments/<skill-name>/<profile>/
        ├── <lock-digest>/
        └── current -> <lock-digest>
```

Node 二进制独立版本化。Skill Environment 是按 profile 和 lock digest 生成的本地
运行视图，不是第三类下载资源。

重复安装同一 Skill 是幂等操作：有效缓存和已满足 lock 的 Node 会直接复用。

## 5. Gateway Tool API

PAOS Agent 通过 Forge Tool Client 使用 Gateway 的 Tool API：

| Method | Path | 用途 |
|:-------|:-----|:-----|
| GET | `/tools` | 列出已注册 Tool |
| GET | `/tools/{tool_id}` | 获取 ToolSpec |
| GET | `/tools/{tool_id}/context` | 获取 readiness 和运行上下文 |
| POST | `/tools/{tool_id}:invoke` | 调用 Query 或启动 Action |
| POST | `/tools/{endpoint_id}/{operation}:invoke` | 按 Endpoint operation 调用 |
| GET | `/invocations/{invocation_id}` | 查询 Action 状态 |
| GET | `/invocations/{invocation_id}/result` | 获取 Action 结果 |
| POST | `/invocations/{invocation_id}/cancel` | 取消 Action |
| GET | `/invocations/{invocation_id}/events` | 获取执行事件 |

Gateway 根据 `endpoint_id + operation` 把 ToolCall 路由到对应 ToolEndpoint。Endpoint
通过 `forge.tool.endpoint/v1alpha1` Wire 与 Gateway 交换注册、调用、状态、结果、控制
和事件消息。

Query 返回同步终态结果；Action 返回 invocation identity，后续通过状态和结果接口完成
闭环。ToolEndpoint 的执行状态由 Provider/Policy Node 管理，Gateway 不实现机器人领域
逻辑。

## 6. 本地 Skill 开发闭环

准备开发环境：

```bash
cd PhyAgentOS
uv sync
uv run paos skill --help
dora --version
```

Skill 源码至少包含：

```text
<skill>/
├── SKILL.md
├── skill.yaml
├── profiles/<profile>/{dataflow.yaml,*.yaml}
└── assets/
```

打包并校验：

```bash
uv run python scripts/package_skill.py \
  examples/forge-skills/move-arm-by-ee \
  --output-dir dist
```

打包脚本会重新生成 `archive-manifest.json`、创建确定性 Bundle、安全解包复核，并输出
归档 SHA-256 与 `size_bytes`。

通过与 Registry 安装相同的 Node 解析和环境构建链路安装本地 Bundle：

```bash
uv run paos skill install dist/move-arm-by-ee-0.2.0.tar.gz
uv run paos skill inspect move-arm-by-ee
uv run paos skill start move-arm-by-ee --profile mujoco
uv run paos skill status move-arm-by-ee
uv run paos skill stop move-arm-by-ee
```

本地闭环不需要 TOS 账号：Skill Bundle 从 `dist/` 读取，尚未满足的 Node lock 仍由
Registry 解析下载。

## 7. Node 与 Skill 发布边界

开发新 Node 时：

1. 在 Node 独立仓库完成代码、单测和 dataflow 集成测试；
2. 构建单可执行文件的平坦 `.tar.gz`；
3. 发布不可覆盖的 GitHub Release Asset；
4. 在资源目录登记 `artifact_id + download_url`；
5. 将 GitHub Asset digest 写入 `skill.yaml`；
6. 重建并验证 Skill Bundle。

Skill Bundle 包含 Skill 配置、profiles、资产、模型和 `SKILL.md`，上传到不可覆盖的
TOS 对象键。确认所有 Node lock 已登记后，再把 Skill URL、SHA-256 和大小登记到资源
目录。

## 8. 验收清单

```text
[ ] skill search 能发现已发布 Skill
[ ] skill install 显示确认和下载进度
[ ] Bundle 与全部 Node 校验通过
[ ] 重复 install 不重复下载已满足的 Node
[ ] skill inspect 显示正确 name/version 和 lock
[ ] skill start 成功
[ ] skill status 显示 Gateway 和 Tool ready
[ ] Agent 能完成 Query/Action Tool 调用
[ ] skill stop 后无残留进程
```

## 相关文档

- [Skill 协作开发流程](skill-development-workflow.md)
- [Skill Bundle 人工发布流程](skill-bundle-publishing.md)
- [move-arm-by-ee 人工发布示例](../../examples/forge-skills/move-arm-by-ee-manual-publishing.md)
- [move-arm-by-ee 快速开始](../../examples/quick_start.md)
- [框架介绍](../zh/01-framework-introduction.md)
- [用户手册](../zh/02-user-manual.md)
- [开发者手册](../zh/03-developer-manual.md)
