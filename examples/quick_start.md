# move-arm-by-ee 快速开始

PAOS 通过统一 Resource Registry API 安装 Skill，不直接读取仓库索引，也不需要节点源码。
参考源码位于 `examples/forge-skills/move-arm-by-ee/`，它不会进入 PAOS wheel，不能视为已安装
Skill。

## 1. 资源目录服务

PAOS 默认使用 `https://paos-resource-manager.dev.x-era.com`，拉取并安装 PAOS 后无需额外
配置即可使用。私有部署可在 `~/.PhyAgentOS/config.json` 中覆盖：

```json
{
  "resourceRegistry": {
    "url": "https://registry.example.com"
  }
}
```

也可以用环境变量临时覆盖；环境变量优先级最高：

```bash
export PAOS_RESOURCE_REGISTRY_URL=https://registry.example.com
```

Registry 只返回下载元数据：

- Skill Bundle 存储在 TOS；Registry 返回 URL、SHA-256 和大小；
- 仅含一个可执行文件的 Node `.tar.gz` 存储在 GitHub Release；Registry 按 `artifact_id`
  返回不可变 URL；
- Node 的平台、版本、入口文件和 GitHub `.tar.gz` Asset SHA-256 由 Skill Bundle 内的
  lock 固定。

## 2. 安装

```bash
paos skill search move-arm-by-ee
paos skill install move-arm-by-ee
paos skill inspect move-arm-by-ee
```

`install` 会先显示 Skill Bundle 的来源、大小和后续 Node 下载提示，并要求 `y/N` 确认。
自动化环境可使用 `paos skill install move-arm-by-ee --yes`。

`install` 下载当前 Skill Bundle并校验 SHA-256，读取 Node lock，只下载本地缺失或不满足
lock 的 Node `.tar.gz`。PAOS 校验 host 与 GitHub Asset SHA-256，要求归档根目录只有一个
与 `entrypoint` 同名的二进制，安全提取、设置执行权限并原子安装。全部节点就绪后才原子
替换 Skill，失败不会替换旧版本。

安装位置：

```text
~/.PhyAgentOS/
├── skills/move-arm-by-ee/
└── forge_runtime/
    ├── nodes/<node-id>/versions/<artifact-id>/
    └── environments/move-arm-by-ee/<profile>/<lock-digest>/
```

重复执行安装时，PAOS 会跳过已满足 lock 的 Node；若当前 Skill manifest 与节点均就绪，
不会重复提交安装。

## 3. 运行 MuJoCo Demo

```bash
paos skill start move-arm-by-ee --profile mujoco
paos skill status move-arm-by-ee
paos agent -m "将夹爪向前移动5cm"
paos skill stop move-arm-by-ee
```

启动时 PAOS 根据 Node lock 生成 Skill Environment。Environment 是本地运行视图，不是第三类
下载资源。

## 4. 发布协作摘要

1. 节点仓 CI 将单个可执行程序打成平坦 `.tar.gz`，发布为不可覆盖的 GitHub Release
   asset。
2. 在资源服务 `resources/nodes.yaml` 登记 `artifact_id + download_url`。
3. Skill 开发者从 GitHub API读取 `.tar.gz` Asset digest，在 `skill.yaml` 锁定
   `artifact_type: executable_tar_gz`、`entrypoint` 和 `sha256`，再收集配置、资产、
   模型与 `SKILL.md`。
4. 上传到 TOS 不可覆盖对象键，回读并计算 SHA-256 与大小。
5. 确认全部 Node lock 已登记后，在 `resources/skills.yaml` 更新该 Skill 的当前条目。
6. 重启静态资源目录服务，再执行本页安装和 MuJoCo smoke。

完整人工发布流程见 `docs/forge/skill-bundle-publishing.md`。
