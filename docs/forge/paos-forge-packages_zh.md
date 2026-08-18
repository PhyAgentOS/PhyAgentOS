# PAOS Forge 包索引规范

`paos-forge-packages.yaml` 是机器可读发布索引，Schema 为
`paos-forge-packages.schema.json`。Schema v2 不再发布 Skill 专属的单体
`runtime_bundle`，资源仅分为 `skill_bundle` 与 `node_bundle`。

## Node Bundle

每个 Forge 节点按 `(node_id, version, platform, arch)` 独立构建、下载、校验和安装。
归档根包含：

```text
node-manifest.json
<binary 或 node 私有目录>
archive-manifest.json
```

安装器会移除仅用于传输校验的 `archive-manifest.json`，并将其余内容原子安装到：

```text
~/.PhyAgentOS/forge_runtime/nodes/<node_id>/versions/<artifact_id>/
```

`node-manifest.json` 固定文件 SHA-256、大小、节点版本、目标平台以及稳定 entrypoint。
不同版本不会覆盖，可以被不同 Skill 同时引用。

## Skill Bundle

Skill Bundle 是可搬迁、自包含的任务层资源，安装到：

```text
~/.PhyAgentOS/skills/<skill_name>/
```

它包含：

- `skill.yaml` 与 `SKILL.md`；
- profile dataflow；
- Tool/Gateway/控制器/仿真配置；
- URDF、MJCF、纹理等 Skill 专属资产；
- 精确的 Node Bundle lock。

dataflow 和 `required_assets` 相对 Skill Bundle 根目录解析；`required_binaries` 是稳定
entrypoint 名称，不再指向单体 Runtime 目录。

## Skill Environment

PAOS 启动 Skill 前验证所有 node lock，并生成不可变执行视图：

```text
~/.PhyAgentOS/forge_runtime/environments/
  <skill>/<profile>/<lock-digest>/
    runtime-lock.json
    bin/<entrypoint> -> ../../../../../nodes/.../<binary>
```

本地符号链接由 PAOS 创建，不进入任何下载归档。启动 Dora 时：

```text
FORGE_RUNTIME_BIN=<environment>/bin
PAOS_SKILL_ROOT=~/.PhyAgentOS/skills/<skill>
```

由于已运行的 Dora daemon 不会继承后续 CLI 进程的新环境变量，PAOS 还会在 environment
的 `launch/` 下生成 dataflow 副本，将 binary 路径渲染为该 lock 对应的绝对路径；配置
文件和 assets 仍链接回已校验的 Skill Bundle。原始 Skill dataflow 保持不变。

因此节点可以独立更新，而 Skill 只有在 lock 更新并重新验证后才切换版本；正在运行的
Skill 不会被“latest”或全局 `current` 隐式改变。

## 下载与安全

- 后台 URL 优先于 GitHub Release URL；两者均为空时视为尚未发布。
- 归档下载后先验证压缩文件大小和 SHA-256。
- 解包时拒绝绝对路径、`..`、链接、特殊文件、重复/Unicode/大小写冲突和压缩炸弹。
- Node manifest、Skill manifest、inventory 和 entrypoint 必须全部验证后才原子提交。
- 下载缓存按归档 SHA-256 去重，多个 Skill 可以复用同一 Node Bundle。
