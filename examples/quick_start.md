# move-arm-by-ee Skill Demo Quick Start

本文说明如何通过静态索引、GitHub Release 或 PAOS Resource Registry 下载、安装并运行
`move-arm-by-ee`。目标机不需要 Forge 节点源码。

## 1. 发布物

需要发布两类不可变的 `tar.gz`：

- 一个 Skill Bundle：包含 `skill.yaml`、`SKILL.md`、MuJoCo profile、配置和资产；
- 九个 Node Bundle：由 Skill Bundle 中 `skill.yaml` 的 `artifacts.nodes` 精确锁定。

对象存储中的文件名可以自定义，每个归档必须有稳定的 HTTPS 下载地址。GitHub Release
等可信直链不要求额外的大小或 SHA-256 字段；通过自建 Backend 下载时，由 Backend
元数据返回 SHA-256。

不要把下载地址写入 `skill.yaml`。该文件只保存 Node 的
`artifact_id/version/platform/arch`；受校验的 Backend 节点可额外固定 `digest`。

## 2. 下载链接填写位置

无服务端阶段，PAOS 通过 `--index` 直接读取
`docs/forge/paos-forge-packages.yaml`，并使用其中的 `direct_download_url`。索引可以是
本地路径或 HTTPS URL：

```bash
paos skill search move-arm-by-ee --index docs/forge/paos-forge-packages.yaml
paos skill install move-arm-by-ee --version 0.2.0 \
  --index docs/forge/paos-forge-packages.yaml
```

资源服务上线后，PAOS 改为读取 Registry API：

```text
GET /v1/skills/move-arm-by-ee/0.2.0
GET /v1/forge-nodes/<artifact-id>
```

发布清单 `docs/forge/paos-forge-packages.yaml` 中：

- GitHub Release 等可信直链填写 `direct_download_url`，客户端不校验大小或 SHA-256；
- 自建资源服务填写 `backend_url`，SHA-256 由服务端元数据响应提供，不写入 YAML；
- 两者同时存在时优先使用 `backend_url`。

静态索引只负责资源定位，不保存下载状态，也不执行依赖解析。依赖以 Skill Bundle 内
`skill.yaml` 的 Node lock 为准。

## 3. 配置 PAOS Registry

PAOS 只配置 Registry 服务根地址，不配置每个归档的 URL。默认配置文件为
`~/.PhyAgentOS/config.json`：

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

对象存储应支持 HTTPS。Backend 下载归档按服务端 SHA-256 缓存；直链下载按 URL/ETag
缓存到 `~/.PhyAgentOS/cache/`。

## 4. 下载和安装

```bash
INDEX=docs/forge/paos-forge-packages.yaml
paos skill search move-arm-by-ee --index "$INDEX"
paos skill install move-arm-by-ee --version 0.2.0 --index "$INDEX"
paos skill inspect move-arm-by-ee
```

安装命令会：

1. 从静态索引定位并下载 Skill Bundle；
2. 读取 `skill.yaml` 中的九个 Node lock；
3. 跳过本地已有且满足 lock 的节点；
4. 定位并下载缺失的 Node Bundle；
5. 原子安装 Skill 和各节点。

GitHub Release 可以只包含裸二进制；PAOS 根据静态索引的 `inventory` 和 `entrypoints`
生成本地 `node-manifest.json`。直链安装保留安全解包检查，但不要求归档携带
`archive-manifest.json`。

安装位置：

```text
~/.PhyAgentOS/
├── skills/move-arm-by-ee/
└── forge_runtime/nodes/<node-id>/versions/<artifact-id>/
```

## 5. 运行 Demo

```bash
paos skill start move-arm-by-ee --profile mujoco
paos skill status move-arm-by-ee
paos agent -m "将夹爪向前移动5cm"
paos skill stop move-arm-by-ee
```

启动时 PAOS 根据 Node lock 在本地生成 Skill Environment；Environment 是本地运行视图，
不是第三类下载包。

## 6. 当前服务端对接要求

PAOS 客户端按 `skill_bundle + node_bundle` 工作。Resource Registry 必须提供
`/v1/forge-nodes/<artifact-id>`，并在 Backend 下载元数据中返回归档 SHA-256。

若资源服务仍使用旧的 `runtime_bundle` 数据模型和
`/v1/forge-runtimes/<artifact-set-id>`，需要先升级为 `node_bundle` 模型和 Forge Node
查询接口，否则 Skill Bundle 可以下载，但九个独立节点无法由
`paos skill install` 自动解析和安装。
