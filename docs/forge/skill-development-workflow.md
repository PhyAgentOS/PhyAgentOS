# Skill 协作开发流程（开发者指南）

本文面向参与 Skill 协作开发的开发者，定义从本地开发、打包、发布到闭环验收的端到端
流程。与 [`skill-bundle-publishing.md`](skill-bundle-publishing.md)（人工发布的格式与
登记细则）和 `examples/forge-skills/move-arm-by-ee-manual-publishing.md`（示例全流程）
的分工：本文是「开发协作流程」，那两份是「发布规范」——涉及格式细节时以它们为准。

当前架构下的核心里程碑是**跑通本地安装闭环**（§1.4）：Skill 开发、Node 复用与打包
验证都可以在本地完成，不依赖 TOS 账号或资源管理端自助配置（§3、§4 待补全）。

## 0. 环境与前置条件

```text
- Linux x86_64
- Python 3.11+ 与 uv
- dora（skill start 需要，运行时会在 PATH 中检查）
- PhyAgentOS 仓库 clone（本地打包脚本与 CLI 来源）
- 可访问的 Resource Registry（复用已登记 Node 时）
- GitHub 仓库写权限（发布新 Node 时；Node 开源仓库组织为
  https://github.com/Forgelab-Robotics）
```

开发环境准备：

```bash
cd PhyAgentOS                     # 仓库根目录
uv sync
uv run paos skill --help          # 确认 CLI 可用
dora --version                    # skill start 前置检查

# 默认使用 https://paos-resource-manager.dev.x-era.com
# 本地或私有 Registry 可通过环境变量覆盖（优先级最高）
export PAOS_RESOURCE_REGISTRY_URL=http://127.0.0.1:8080
```

## 1. Skill 与 Node 开发、本地闭环

### 1.1 Skill 源码开发

按 `skill-bundle-publishing.md` §1.1 的目录结构组织 Skill 源码，至少包含：

```text
<skill>/
├── SKILL.md
├── skill.yaml
├── profiles/<profile>/{dataflow.yaml,*.yaml}
└── assets/
```

`skill.yaml` 要点：

- `name/version` 为发布身份，改动内容后递增版本；
- `profiles` 声明可启动 profile 与 `required_binaries/required_assets`；
- `artifacts.resolver: registry`，每个 Node 固定
  `artifact_id/version/platform/arch/artifact_type/entrypoint/sha256`。

### 1.2 Node 的两种开发路径

Skill Bundle 只包含 Skill 文件，Node 二进制经 Registry 解析下载。开发时二选一：

**A. 复用已登记 Node（推荐起步）**

直接把 `examples/forge-skills/move-arm-by-ee/skill.yaml` 中对应 Node 的 lock 条目
（`artifact_id` 与 `sha256`）拷入自己的 skill.yaml。这些 artifact_id 已登记在资源
管理端，本地 install 即可从 Registry 解析，无需发布任何 Node。

**B. 开发新 Node**

1. 在 Node 自己的仓库（https://github.com/Forgelab-Robotics 组织下）完成代码开发
   与测试（单测、本地 dataflow 集成）；
2. 按 §2 打包并发布 Release 资产；
3. 资源管理端登记 `nodes.yaml`（§4，当前由维护者完成）；
4. 将 GitHub digest 写入 skill.yaml lock，再回到本地闭环验证。

### 1.3 Skill 打包

```bash
cd PhyAgentOS                     # 仓库根目录
uv run python scripts/package_skill.py <skill-dir> --output-dir dist
```

脚本重新生成 `archive-manifest.json`、构建确定性 `.tar.gz`、用 `ArchiveValidator`
安全解包复核，并打印归档 `sha256` 与 `size_bytes`。软/硬链接会被拒绝；同名 bundle
拒绝覆盖（`--force` 显式覆盖）。详细行为见 `skill-bundle-publishing.md` §4。

### 1.4 本地安装闭环（当前架构的验收标准）

打包后直接以本地 bundle 走完整安装与启动流程：

```bash
export PAOS_RESOURCE_REGISTRY_URL=<registry>

paos skill install dist/<name>-<version>.tar.gz   # 自动识别本地包，或用 --local
paos skill install dist/<name>-<version>.tar.gz   # 幂等复跑：already ready
paos skill inspect <name>
paos skill start <name> --profile <profile>
paos skill status <name>
paos skill stop <name>
```

本地包安装与注册表安装行为一致：整包 SHA-256 + manifest 逐文件校验、未满足的 Node
lock 经 Registry 解析下载、失败不破坏已安装版本。

**闭环验收清单：**

```text
[ ] install 成功，输出的归档 sha256/size 与打包脚本一致
[ ] 九个（或全部）Node 下载校验通过，forge_runtime/nodes/ 下回执与二进制就位
[ ] 幂等复跑 install 输出 already ready，无重复下载
[ ] inspect 显示 name/version 与发布身份一致
[ ] start 成功，status 显示 Gateway GET /tools: ready、全部 Tool context ready
[ ] stop 成功，无残留进程
```

## 2. Node 代码与 Release 包上传

仅「开发新 Node」路径需要本节；复用已登记 Node 可跳过。

1. **代码入库**：Node 源码推送到其仓库（https://github.com/Forgelab-Robotics
   组织下；分支/PR 按该仓库规范）；
2. **Release 资产**：打版本 tag，创建 GitHub Release，上传 `<name>.tar.gz` 资产。
   资产必须满足：
   - 归档根目录只有**一个**与 `entrypoint` 同名的普通文件，无包裹目录、无软/硬链接；
   - Release 提供 `sha256:<64 hex>` 格式的不可变 `digest`；
   - tag、Asset、`artifact_id` 一经发布不可覆盖，修正必须升版本。

   自检：

   ```bash
   tar -tzf <name>.tar.gz          # 结果只能是单行 <name>
   gh api repos/<owner>/<repo>/releases/tags/<tag> \
     --jq '.assets[] | select(.name == "<name>.tar.gz") | {url: .browser_download_url, digest}'
   ```

3. **回读验证**：下载最终 URL 校验 sha256 后再交付：

   ```bash
   curl -fL "<browser_download_url>" -o ./<name>.tar.gz
   echo "<64位hex>  ./<name>.tar.gz" | sha256sum -c -
   ```

## 3. Skill Bundle 上传 TOS

将 `dist/<name>-<version>.tar.gz` 上传到不可覆盖对象键：

```text
skill-bundles/<name>/<version>/<name>-<version>.tar.gz
```

上传后必须从最终 HTTPS URL 回读并校验 sha256/size 与本地一致。

> **TODO**：TOS 上传账号与方式由仓库维护者后续补充，此处暂为占位。账号到位前，
> 以 §1.4 本地安装闭环作为开发交付物即可——本地 bundle 与未来 TOS 对象内容完全
> 一致，账号到位后直接上传同一文件。

## 4. 资源管理端配置（待实现）

> **状态：待实现。** 协作者自助登记 Node/Skill 的流程尚未开放。当前
> `paos-resource-manager/resources/` 下的 `nodes.yaml`、`skills.yaml` 由仓库维护者
> 集中维护，修改后需重启静态服务才生效。

在自助流程落地前：

- 复用已登记 Node 的开发者**不需要**任何资源管理端配置，跑通 §1.4 本地 install
  即达成开发里程碑；
- 新 Node 的 `nodes.yaml` 登记与 Skill 的 `skills.yaml` 登记由维护者协助完成，
  开发者交付 `artifact_id`、Release URL、digest（Node）或 bundle sha256/size（Skill）
  即可，登记细节见 `skill-bundle-publishing.md` §7。

预留内容（自助流程落地后补充）：登记 API/表单、权限控制、服务重启与灰度验证步骤。

## 5. 命令闭环测试与支持

### 5.1 完整命令闭环

```bash
paos skill search <name>                              # 注册表可见性
paos skill install <name | 本地bundle路径>             # 注册表或本地包
paos skill install <同一目标>                          # 幂等复跑
paos skill inspect <name>                             # 安装身份与 lock
paos skill start <name> --profile <profile>           # 启动 dataflow
paos skill status <name>                              # 状态与 Tool ready 检查
paos skill logs <name> --lines <n>                    # 生命周期日志
paos skill stop <name>                                # 停止
```

### 5.2 建议覆盖的异常场景

```text
[ ] 篡改本地 bundle 内容（保留原 manifest）→ 逐文件校验失败，旧版本保留
[ ] Registry URL 不可达 → 安装明确报错，不产生半安装状态
[ ] PATH 缺少 dora → start 报错提示安装 dora
[ ] 重复 install 幂等；stop 后可再次 start
[ ] Node 下载中断后重试可恢复（断点续传/缓存）
```

### 5.3 交付与支持

开发完成时提交的交付物应包含：

- Skill 源码位置与 `dist/<name>-<version>.tar.gz` 的路径、sha256、size；
- §1.4 闭环验收清单的执行结果（命令输出）；
- 新 Node 时：仓库、tag、`artifact_id`、GitHub digest、回读校验结果；
- 遇到的问题与复现步骤（注册表 URL、命令、输出）。

问题反馈走仓库 issue，附带上述信息；发布相关问题以
`skill-bundle-publishing.md` §9 的发布顺序为最终依据。
