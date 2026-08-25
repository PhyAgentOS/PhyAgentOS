# Skill Bundle 人工发布流程

本版本不实现 Skill CI、TOS SDK 上传或目录自动更新。本文定义开发者手工生成、上传、登记
和验收 Skill Bundle 的统一流程，覆盖最新落地的本地打包脚本、本地包安装、目录结构和
发布后验收。示例以 `move-arm-by-ee` 为参照（源码见
`examples/forge-skills/move-arm-by-ee/`）。

## 1. 目录结构总览

### 1.1 Skill 源码目录

权威仓中的标准 Skill 源码布局（以 `move-arm-by-ee` 为例）：

```text
<skill>/
├── SKILL.md                   # Agent 使用的 Skill 说明文档
├── skill.yaml                 # Skill 清单与 Node lock
├── README.md                  # 可选，开发者说明
├── THIRD_PARTY_NOTICES.md     # 可选，第三方资产声明
├── archive-manifest.json      # 打包脚本生成，逐文件记录 SHA-256
├── profiles/
│   └── <profile>/             # 每个可启动 profile 一个目录
│       ├── dataflow.yaml
│       └── *.yaml             # 各 node 的配置（controller/gateway/...）
└── assets/                    # URDF、MJCF、网格、提示词等资产
```

### 1.2 打包输出

```text
PhyAgentOS/
├── dist/
│   └── <name>-<version>.tar.gz          # 标准 Skill Bundle（上传 TOS 的发布物）
└── dist/forge/quick-start/              # 可选：离线快速安装包
    ├── <name>-quick-start-<version>-linux-x86_64/
    │   ├── quick_start.sh               # 校验 SHA256SUMS 后离线安装并启动
    │   ├── SHA256SUMS                   # 包内全部文件的 SHA-256
    │   ├── bundle-manifest.json
    │   ├── bundles/nodes/<artifact_id>.tar.gz    # 九个 Node 归档镜像
    │   ├── bundles/<name>-skill-<version>-node-lock.tar.gz  # Skill Bundle 镜像
    │   └── packages/<wheel>.whl         # 可选：paos CLI 的兜底 wheel
    └── <name>-quick-start-<version>-linux-x86_64.tar.gz
```

quick-start 是注册表分发的离线镜像：`bundles/nodes/` 下就是 Registry 为各
`artifact_id` 提供的同一份不可变 GitHub Release 资产。离线安装后
`paos skill start` 可正常工作；维护它时须同步重建 `SHA256SUMS` 与
`bundle-manifest.json`。

### 1.3 注册表与存储

```text
paos-resource-manager/
└── resources/
    ├── nodes.yaml      # artifact_id -> GitHub Release download_url
    └── skills.yaml     # Skill name -> TOS download_url + sha256 + size_bytes

TOS 对象键（不可覆盖）：
skill-bundles/<name>/<version>/<name>-<version>.tar.gz
```

注册表是静态目录服务，PAOS 通过统一 Resource Registry API 读取（`/v1/skills/<name>`、
`/v1/forge-nodes/<artifact_id>`、`/health/ready`），不直接读仓库 YAML。

### 1.4 安装后的 PAOS HOME

```text
~/.PhyAgentOS/
├── skills/<name>/                        # 已安装的 Skill 文件
├── cache/
│   ├── <sha256>/archive.tar.gz           # Skill Bundle 下载缓存（内容寻址）
│   └── direct/<urlhash>/artifact.download # Node 下载缓存（目录名是 URL 哈希）
└── forge_runtime/
    ├── nodes/<node-id>/versions/<artifact-id>/
    │   ├── .paos-node.json               # 安装回执（NodeInstaller 写入）
    │   └── <entrypoint>                  # 唯一可执行二进制
    └── environments/<name>/<profile>/
        ├── <lock-digest>/                # 内容寻址的运行时环境
        └── current -> <lock-digest>
```

## 2. 源码与标准 Bundle

标准 `.tar.gz` 根目录必须直接包含：

```text
archive-manifest.json
skill.yaml
SKILL.md
profiles/...
assets/...
```

不要增加包裹层目录。`archive-manifest.json` 必须逐项记录除自身外所有文件的相对路径、
字节数和 SHA-256。禁止绝对路径、`..`、软/硬链接和特殊文件。

`skill.yaml` 必须：

- 使用当前 `manifest_version`（示例为 2）；
- 让 `name/version` 与发布身份一致；
- 将 `skill_document` 设为 `SKILL.md`；
- 声明可启动 profile、required binaries/assets/environment，以及
  `required_tools`、`gateway_url` 等运行时字段；
- 对每个 Node 固定
  `artifact_id/version/platform/arch/artifact_type/entrypoint/sha256`。

当前 `artifact_type` 只支持 `executable_tar_gz`：Node Release Asset 必须是 `.tar.gz`，
归档根目录中只能有一个与 `entrypoint` 同名的可执行二进制；不要求
`archive-manifest.json` 或 `node-manifest.json`。`sha256` 必须取自 GitHub Release
`.tar.gz` Asset 的不可变 `digest` 字段。发布 Skill 前，所有 lock 必须已在资源服务
`resources/nodes.yaml` 登记。

保留 `artifact_type` 是为了未来增加多文件 archive、模型目录等安装器；当前客户端遇到非
`executable_tar_gz` 类型会明确拒绝，不会猜测解包规则。

可通过 GitHub API读取摘要：

```bash
gh api repos/<owner>/<repo>/releases/tags/<tag> \
  --jq '.assets[] | select(.name == "<binary-name>.tar.gz") | {url: .browser_download_url, digest}'
```

`digest` 必须存在且以 `sha256:` 开头；写入 `skill.yaml` 时去掉此前缀。禁止用本地重算值
替代 GitHub 返回值后继续沿用同一 `artifact_id`。

## 3. 资产与模型

运行必需的配置、URDF、MJCF、提示词、小型数据和模型均随 Skill Bundle 发布。大型推理模型
也可以整体进入 TOS Skill Bundle，但不进入 PhyAgentOS 仓库。

不得打包：

- TOS、GitHub、模型仓或机器人凭据；
- 预签名 URL；
- 本机绝对路径、缓存、日志和运行状态；
- 未获得发布许可的数据或模型。

## 4. 本地打包与检查

推荐使用 PhyAgentOS 仓库提供的打包脚本：重新生成 `archive-manifest.json`、构建确定性
`.tar.gz` 并完成校验：

```bash
cd PhyAgentOS
uv run python scripts/package_skill.py <skill-dir> \
  [--output-dir dist] [--version <v>] [--force] [--no-validate]
```

输出为 `<output-dir>/<name>-<version>.tar.gz`，stdout 打印归档 `sha256` 与
`size_bytes`（登记 `skills.yaml` 时使用）。脚本行为：

- 拒绝软链接、硬链接和绝对路径；
- 重新生成 `archive-manifest.json`（除自身外全部文件的相对路径/字节数/SHA-256）；
- 使用 GNU tar（`--sort=name`、固定 mtime/owner/group）与 `gzip -n` 生成确定性归档；
- 用 `ArchiveValidator` 安全解包到临时目录并重新验证文件集合与摘要；
- 已存在的同名 bundle 拒绝覆盖，除非显式 `--force`（已发布物不可变）。

若仓库尚无打包脚本，至少应执行：

1. 确认每个 Node `.tar.gz` 解压后只有根目录下的同名二进制；
2. 从 GitHub Release API读取每个 `.tar.gz` Asset 的 `digest`，要求格式为
   `sha256:<64 hex>`；
3. 将去掉 `sha256:` 前缀的值写入对应 Node lock，并校验所有 profile 引用；
4. 收集完整 Skill payload；
5. 为每个 Skill 文件计算 SHA-256/大小并生成 `archive-manifest.json`；
6. 以平坦根目录创建 Skill `tar.gz`；
7. 安全解包到临时目录并重新验证文件集合和摘要。

手工构建确定性归档时，不能把 `.` 本身作为 tar 参数（该成员会被归档校验器拒绝），
应逐项列出顶层条目：

```bash
tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
  -C <skill-dir> -cf - $(ls -A <skill-dir>) \
  | gzip -n > dist/<name>-<version>.tar.gz
```

计算最终归档元数据：

```bash
sha256sum <name>-<version>.tar.gz
stat -c '%s' <name>-<version>.tar.gz
```

这里的归档 SHA-256 用于 TOS Skill 下载校验；Node lock 的 SHA-256 则校验 GitHub 上的
Node `.tar.gz`，两者不是同一个摘要。PAOS 校验 Node 归档后安全提取唯一二进制，并在本地
记录提取后二进制摘要用于后续就绪检查。

## 5. 发布前本地安装验证

上传 TOS 之前，可以直接用本地 bundle 走完整的安装与启动流程。`paos skill install`
同时接受注册表名称与本地 bundle 路径：

```bash
export PAOS_RESOURCE_REGISTRY_URL=<registry>

paos skill install --local dist/<name>-<version>.tar.gz  # 显式本地安装
paos skill install dist/<name>-<version>.tar.gz          # 自动识别，等效
paos skill install dist/<name>-<version>.tar.gz          # 幂等，输出 already ready
paos skill inspect <name>
paos skill start <name> --profile <profile>
paos skill status <name>
paos skill stop <name>
```

自动识别规则：参数是存在的文件路径、以 `.tar.gz`/`.tgz` 结尾或包含路径分隔符时按本地
bundle 处理，否则按注册表名称查询。注册表名称是目录安全串，不会误判。

本地安装行为与注册表安装完全一致，仅 Skill 归档来源不同：

- bundle 整包 SHA-256 校验 + `archive-manifest.json` 逐文件校验全部保留；
- 未满足的 Node lock 仍通过 `PAOS_RESOURCE_REGISTRY_URL` 解析和下载；
- 安装失败（含摘要校验失败）不会破坏已安装的旧版本；
- 重复安装已满足 lock 的 Skill 不重复下载、不重复提交，输出 already ready；
- 同版本再次安装会替换并保留时间戳备份（升级路径），正式发布物建议升版本。

## 6. 上传 TOS

通过火山云控制台或已有上传工具，上传到不可覆盖对象键：

```text
skill-bundles/<name>/<version>/<name>-<version>.tar.gz
```

对象应提供长期 HTTPS URL。禁止把凭据或短期预签名 URL写入静态目录。上传后必须从最终
HTTPS URL 回读文件，再次验证字节数和 SHA-256 与本地归档一致：

```bash
curl -fL "https://<tos-domain>/skill-bundles/<name>/<version>/<name>-<version>.tar.gz" \
  -o ./<name>-<version>-verify.tar.gz
sha256sum ./<name>-<version>-verify.tar.gz
stat -c '%s' ./<name>-<version>-verify.tar.gz
```

## 7. 登记当前 Skill

在资源目录服务 `resources/skills.yaml` 中，每个 Skill 名称只维护一个当前条目：

```yaml
schema_version: 1
skills:
  - name: move-arm-by-ee
    description: Relative end-effector motion and gripper control demo
    download_url: https://<tos-domain>/skill-bundles/move-arm-by-ee/0.2.0/move-arm-by-ee-0.2.0.tar.gz
    sha256: <64位归档SHA-256>
    size_bytes: <归档字节数>
```

`sha256` 与 `size_bytes` 必填（`mode=verified` 下载校验依赖二者）。登记前逐个确认
`skill.yaml` 中的 Node `artifact_id` 已存在于 `resources/nodes.yaml`，并再次确认 lock 的
SHA-256 与 GitHub API 当前返回的 Asset digest 一致。提交目录变更并通过资源服务测试后
重启服务——静态目录服务不热更新，不重启不会读到新 YAML。

## 8. 发布后验收

```bash
export PAOS_RESOURCE_REGISTRY_URL=https://registry.example.com

curl -fsS "$PAOS_RESOURCE_REGISTRY_URL/health/ready"
paos skill search <name>
paos skill install <name>
paos skill inspect <name>
paos skill start <name> --profile <profile>
paos skill status <name>
paos skill stop <name>
```

验收应确认：

- `/health/ready` 返回 200；
- `/v1/skills/<name>` 返回登记一致的 `download_url/sha256/size`，`mode=verified`；
- `/v1/forge-nodes/<artifact_id>` 对九个 Node 均可解析，`mode=direct`；
- Skill 下载 SHA-256 与大小匹配，下载缓存为 `<sha256>/archive.tar.gz`；
- 只下载缺失或不满足 lock 的 Node；
- Node host、归档结构、entrypoint、执行权限和 GitHub `.tar.gz` SHA-256 全部通过，
  安装后 `forge_runtime/nodes/<node-id>/versions/<artifact-id>/` 含
  `.paos-node.json` 回执与同名二进制；
- Environment 可以准备，dataflow 中不存在源码仓绝对路径；
- profile smoke 完成（示例中 Gateway 的三个 Tool 均 ready）；
- 重复执行 `install` 显示当前 Skill 已就绪，不重复提交。

若安装在 Node 下载或验证阶段失败，旧 Skill 必须保持不变。修复发布物或目录后重试，不覆盖
既有 Node `artifact_id`、GitHub Release Asset 或 TOS 对象键。

## 9. 发布顺序

严格按照以下顺序执行：

```text
发布 Node GitHub Release
  -> 校验九个 Node Asset URL 与 digest
  -> 更新 nodes.yaml
  -> 更新 skill.yaml Node lock
  -> 本地打包脚本生成 archive-manifest.json 与标准 Bundle
  -> 本地安装验证（--local / 自动识别，幂等复跑，profile smoke）
  -> 上传并回读 TOS（skill-bundles/<name>/<version>/ 对象键）
  -> 更新 skills.yaml
  -> 测试并重启 Resource Registry
  -> PAOS 注册表安装与 MuJoCo 验收
  -> （维护离线分发时）重建 quick-start 包与 SHA256SUMS
```

任何发布物发生变化，都应使用新的版本、Asset、对象键和 `artifact_id`，不要覆盖既有发布物。
