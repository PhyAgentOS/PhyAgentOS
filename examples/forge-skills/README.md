# Forge Skill 示例

此目录仅保存开发参考源码，不是 PAOS 内置 Skill，也不进入 wheel。复制或拉取 PAOS 代码不会
让这些 Skill 出现在 `~/.PhyAgentOS/skills`。

`move-arm-by-ee/` 展示标准 Skill 源码结构、MuJoCo profile、Node lock 与 `SKILL.md`。正式
发布时应由 Skill 权威仓收集资产并生成标准 Skill Bundle，上传 TOS，再由 Resource Registry
登记。用户通过 `paos skill install <name>` 安装发布物。

本地开发迭代可用仓库根目录的打包脚本生成 bundle，并在发布前直接用本地包验证：

```bash
# 在仓库根目录执行
uv run python scripts/package_skill.py examples/forge-skills/move-arm-by-ee --output-dir dist
paos skill install --local dist/move-arm-by-ee-<version>.tar.gz
```

该 Demo 的 Node GitHub Release 登记、Skill 打包、TOS 上传和 PAOS 验收步骤见
[`move-arm-by-ee-manual-publishing.md`](move-arm-by-ee-manual-publishing.md)。
