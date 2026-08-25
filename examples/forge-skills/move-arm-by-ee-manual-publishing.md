# move-arm-by-ee 人工上传发布指南

本文以 `move-arm-by-ee` 为例，说明在 Node GitHub Release 已就位的前提下，如何从零完成：

1. Node Release Asset 检查与 Registry 登记；
2. Skill Node lock 固定；
3. Skill Bundle 打包与 TOS 上传；
4. Skill Registry 登记；
5. PAOS 下载、安装和 MuJoCo 验收。

本流程不依赖数据库或资源上传 API。GitHub 和 TOS 存储文件，
`paos-resource-manager` 只提供静态下载目录。

## 1. 发布物与源码位置

需要处理两类发布物：

- Node：九个 GitHub Release `.tar.gz` Asset；
- Skill：一个上传到 TOS 的 `move-arm-by-ee-<version>.tar.gz`。

相关文件：

```text
PhyAgentOS/examples/forge-skills/move-arm-by-ee/
paos-resource-manager/resources/nodes.yaml
paos-resource-manager/resources/skills.yaml
```

Demo 使用九个 Node：

```text
gateway
relative_pose_policy
motion_action_policy
gripper_action_policy
motion_server
joint_trajectory_controller
gripper_action_controller
mujoco_sim
image_viewer
```

## 2. 检查 GitHub Node Release

### 2.1 Node Asset 格式

每个 Release Asset 必须满足：

- 文件格式为 `.tar.gz`；
- 归档根目录中只有一个普通文件；
- 文件名必须与 Skill lock 的 `entrypoint` 一致；
- 不包含包裹目录、软链接、`node-manifest.json` 或 `archive-manifest.json`；
- GitHub Release API提供 `sha256:<64 hex>` 格式的 `digest`；
- Release tag、Asset 和后续使用的 `artifact_id` 均不可覆盖。

例如 `gateway.tar.gz`：

```bash
tar -tzf gateway.tar.gz
```

结果只能是：

```text
gateway
```

### 2.2 读取 URL 与 GitHub digest

对每个 Node 执行：

```bash
gh api repos/<owner>/<repo>/releases/tags/<tag> \
  --jq '.assets[]
        | select(.name == "gateway.tar.gz")
        | {url: .browser_download_url, digest}'
```

预期结果：

```json
{
  "url": "https://github.com/<owner>/<repo>/releases/download/v0.2.0/gateway.tar.gz",
  "digest": "sha256:<64位SHA-256>"
}
```

如果 `digest` 缺失，不要用同一个 `artifact_id` 临时填入其他摘要。应重新生成并发布新的
不可变 Asset，必要时提升版本或更换 `artifact_id`。

下载回读验证：

```bash
curl -fL "<browser_download_url>" -o /tmp/gateway.tar.gz
echo "<去掉sha256:前缀的摘要>  /tmp/gateway.tar.gz" | sha256sum -c -
tar -tzf /tmp/gateway.tar.gz
```

这里校验的是完整 `.tar.gz`，不是解压后二进制的摘要。

## 3. 登记 Node

编辑 `paos-resource-manager/resources/nodes.yaml`。`schema_version` 只能出现一次，每个
`artifact_id` 只能出现一次：

```yaml
schema_version: 1
nodes:
  - artifact_id: gateway-0.2.0-linux-x86_64-tar-gz
    download_url: https://github.com/<org>/<gateway-repo>/releases/download/v0.2.0/gateway.tar.gz

  - artifact_id: relative_pose_policy-0.2.0-linux-x86_64-tar-gz
    download_url: https://github.com/<org>/<relative-pose-repo>/releases/download/v0.2.0/relative_pose_policy.tar.gz

  - artifact_id: motion_action_policy-0.2.0-linux-x86_64-tar-gz
    download_url: https://github.com/<org>/<motion-policy-repo>/releases/download/v0.2.0/motion_action_policy.tar.gz

  - artifact_id: gripper_action_policy-0.2.0-linux-x86_64-tar-gz
    download_url: https://github.com/<org>/<gripper-policy-repo>/releases/download/v0.2.0/gripper_action_policy.tar.gz

  - artifact_id: motion_server-0.2.0-linux-x86_64-tar-gz
    download_url: https://github.com/<org>/<motion-repo>/releases/download/v0.2.0/motion_server.tar.gz

  - artifact_id: joint_trajectory_controller-0.2.0-linux-x86_64-tar-gz
    download_url: https://github.com/<org>/<controller-repo>/releases/download/v0.2.0/joint_trajectory_controller.tar.gz

  - artifact_id: gripper_action_controller-0.2.0-linux-x86_64-tar-gz
    download_url: https://github.com/<org>/<gripper-controller-repo>/releases/download/v0.2.0/gripper_action_controller.tar.gz

  - artifact_id: mujoco_sim-0.2.0-linux-x86_64-tar-gz
    download_url: https://github.com/<org>/<mujoco-repo>/releases/download/v0.2.0/mujoco_sim.tar.gz

  - artifact_id: image_viewer-0.2.0-linux-x86_64-tar-gz
    download_url: https://github.com/<org>/<image-viewer-repo>/releases/download/v0.2.0/image_viewer.tar.gz
```

`nodes.yaml` 只保存 `artifact_id + download_url`。Node 的平台、架构、entrypoint 和摘要由
Skill lock 固定，不在 Registry 重复维护。

## 4. 固定 Skill Node lock

编辑 `PhyAgentOS/examples/forge-skills/move-arm-by-ee/skill.yaml`。

将每个零值 `sha256` 替换为对应 GitHub `.tar.gz` Asset 的 digest，写入时去掉
`sha256:` 前缀：

```yaml
artifacts:
  resolver: registry
  nodes:
    gateway:
      artifact_id: gateway-0.2.0-linux-x86_64-tar-gz
      version: "0.2.0"
      platform: linux
      arch: x86_64
      artifact_type: executable_tar_gz
      entrypoint: gateway
      sha256: <gateway.tar.gz的64位SHA-256>
```

其余八个 Node 使用相同结构。发布前确认：

- `artifact_id` 与 `nodes.yaml` 完全一致；
- `entrypoint` 与 Node 归档内唯一文件名一致；
- `platform/arch` 与二进制目标平台一致；
- `profiles.mujoco.required_binaries` 中的九个名称均有唯一 provider；
- 不再存在零值或占位 SHA-256。

## 5. 重新生成 Skill archive manifest

> 自动化：`uv run python scripts/package_skill.py examples/forge-skills/move-arm-by-ee
> --output-dir dist` 会同时完成本节的 manifest 生成与第 6 节的打包/校验。以下手工命令
> 作为参考。

每次修改 Skill 源码、配置、资产或 Node lock 后，都必须重新生成
`archive-manifest.json`：

```bash
cd PhyAgentOS

uv run python - <<'PY'
import hashlib
import json
import os
from pathlib import Path

root = Path("examples/forge-skills/move-arm-by-ee")
files = []

# 用 os.walk 而不是 rglob("*")：后者会漏掉 dotfile，而第 6 节的 tar 会打包
# dotfile，两者不一致会导致校验失败。禁止软/硬链接，与打包脚本行为一致。
for directory, dirnames, filenames in os.walk(root, followlinks=False):
    dirnames.sort()
    for entry in dirnames:
        if (Path(directory) / entry).is_symlink():
            raise SystemExit(f"Skill Bundle 禁止软链接目录: {Path(directory) / entry}")
    for name in sorted(filenames):
        path = Path(directory) / name
        relative = path.relative_to(root).as_posix()
        if relative == "archive-manifest.json":
            continue
        if path.is_symlink() or path.stat().st_nlink > 1:
            raise SystemExit(f"Skill Bundle 禁止软/硬链接: {path}")
        data = path.read_bytes()
        files.append({
            "path": relative,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })

files.sort(key=lambda item: item["path"])
(root / "archive-manifest.json").write_text(
    json.dumps({"files": files}, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"记录 {len(files)} 个文件")
PY
```

## 6. 生成 Skill Bundle

> 自动化：直接运行 `uv run python scripts/package_skill.py examples/forge-skills/move-arm-by-ee
> --output-dir dist`；脚本同时生成 manifest、打包、校验并输出 sha256/size。以下手工命令
> 作为参考。

Skill `.tar.gz` 必须是平坦归档，解压后根目录直接出现 `skill.yaml`、`SKILL.md` 和
`archive-manifest.json`，不能增加 `move-arm-by-ee/` 包裹目录。

```bash
cd PhyAgentOS
mkdir -p dist

tar \
  --sort=name \
  --mtime='UTC 1970-01-01' \
  --owner=0 \
  --group=0 \
  --numeric-owner \
  -C examples/forge-skills/move-arm-by-ee \
  -cf - $(ls -A examples/forge-skills/move-arm-by-ee) \
  | gzip -n > dist/move-arm-by-ee-0.2.0.tar.gz
```

注意：不能把 `.` 本身作为 tar 参数——该成员会被 ArchiveValidator 拒绝；应逐项列出
`ls -A` 的顶层条目。

计算最终 Skill 归档元数据：

```bash
sha256sum dist/move-arm-by-ee-0.2.0.tar.gz
stat -c '%s' dist/move-arm-by-ee-0.2.0.tar.gz
```

记录这两个值，后续分别写入 `skills.yaml` 的 `sha256` 和 `size_bytes`。

本地验证归档：

```bash
uv run python - <<'PY'
import hashlib
import tempfile
from pathlib import Path

from PhyAgentOS.skill_runtime.archive import ArchiveValidator

archive = Path("dist/move-arm-by-ee-0.2.0.tar.gz")
sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
with tempfile.TemporaryDirectory() as directory:
    ArchiveValidator().extract(
        archive,
        Path(directory),
        expected_sha256=sha256,
    )
print("Skill Bundle archive validation passed")
PY
```

## 7. 上传 Skill Bundle 到 TOS

通过 TOS 控制台或既有上传工具，将归档上传到不可覆盖对象键：

```text
skills/move-arm-by-ee/0.2.0/move-arm-by-ee-0.2.0.tar.gz
```

要求：

- 使用长期公开 HTTPS URL；
- 不在目录中保存凭据或短期预签名 URL；
- 不覆盖已经发布的对象键；
- 上传完成后从最终 URL 回读验证。

```bash
curl -fL \
  "https://<tos-domain>/skills/move-arm-by-ee/0.2.0/move-arm-by-ee-0.2.0.tar.gz" \
  -o /tmp/move-arm-by-ee-0.2.0.tar.gz

sha256sum /tmp/move-arm-by-ee-0.2.0.tar.gz
stat -c '%s' /tmp/move-arm-by-ee-0.2.0.tar.gz
```

回读结果必须与本地 `dist/` 归档完全一致。

## 8. 登记 Skill

编辑 `paos-resource-manager/resources/skills.yaml`：

```yaml
schema_version: 1
skills:
  - name: move-arm-by-ee
    description: Relative end-effector motion and gripper control demo
    download_url: https://<tos-domain>/skills/move-arm-by-ee/0.2.0/move-arm-by-ee-0.2.0.tar.gz
    sha256: <Skill tar.gz的64位SHA-256>
    size_bytes: <Skill tar.gz字节数>
```

注意：

- 这里的 `sha256` 是 Skill TOS 归档摘要；
- `skill.yaml` 中各 Node 的 `sha256` 是对应 GitHub Node 归档摘要；
- 两类摘要不可混用；
- `skills.yaml` 每个 Skill 名称只维护一个当前条目。

## 9. 验证并重启 Resource Registry

```bash
cd paos-resource-manager

cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test
docker compose up --build -d
```

静态目录不会热加载。修改 YAML 后必须重启服务。

验证 API：

```bash
curl -fsS "https://<registry>/health/ready"
curl -fsS "https://<registry>/v1/forge-nodes/gateway-0.2.0-linux-x86_64-tar-gz"
curl -fsS "https://<registry>/v1/skills/move-arm-by-ee"
```

Node API 应返回 `download_url/artifact_id/mode=direct`；Skill API 应返回
`download_url/sha256/size/mode=verified`。

## 10. PAOS 端到端验收

在干净机器或隔离的 PAOS HOME 上执行：

```bash
export PAOS_RESOURCE_REGISTRY_URL=https://<registry>

paos skill search move-arm-by-ee
paos skill install move-arm-by-ee
paos skill inspect move-arm-by-ee
```

安装后资源组织应为：

```text
~/.PhyAgentOS/
├── skills/move-arm-by-ee/
└── forge_runtime/
    ├── nodes/<node-id>/versions/<artifact-id>/
    │   ├── .paos-node.json
    │   └── <entrypoint>
    └── environments/move-arm-by-ee/mujoco/<lock-digest>/
```

运行 MuJoCo profile：

```bash
paos skill start move-arm-by-ee --profile mujoco
paos skill status move-arm-by-ee
paos agent -m "将夹爪向前移动5厘米"
paos skill stop move-arm-by-ee
```

验收应确认：

- Skill 归档 SHA-256 和大小验证通过；
- 九个 Node 均能通过 Registry 解析；
- Node `.tar.gz` 摘要、归档结构、entrypoint 和 host 匹配；
- URDF、MJCF 和网格资产完整；
- Gateway 的三个 Tool 均 ready；
- 重复执行 `paos skill install move-arm-by-ee` 不重复安装已满足 lock 的 Node；
- 任一 Node 失败时，不替换已有可用 Skill。

## 11. 发布顺序

严格按照以下顺序执行：

```text
发布 Node GitHub Release
  -> 校验九个 Node Asset URL 与 digest
  -> 更新 nodes.yaml
  -> 更新 skill.yaml Node lock
  -> 重新生成 archive-manifest.json
  -> 生成并验证 Skill Bundle
  -> 上传并回读 TOS
  -> 更新 skills.yaml
  -> 测试并重启 Resource Registry
  -> PAOS 安装与 MuJoCo 验收
```

任何发布物发生变化，都应使用新的版本、Asset、对象键和 `artifact_id`，不要覆盖既有发布物。
