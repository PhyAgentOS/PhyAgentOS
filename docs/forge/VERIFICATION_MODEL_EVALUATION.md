# Verification Service 真实模型语义评估

## 1. 目标与边界

该评估用于回答三个独立问题：真实模型能否持续返回合法 `VerificationVerdict`；它能否正确区分
`success`、`failure`、`replan_required` 和 `inconclusive`；它是否会把 Gateway command success、Markdown
projection 或 Lesson 错当成语义成功证据。

评估只调用正式 `VerificationServiceProcess → provider-spec → model provider` 路径，不连接 Gateway、Dora、
Watchdog、Action 或硬件。评估通过不构成任何运动授权，也不证明抓取放置闭环完成。

## 2. 权威输入

- `semantic_verifier_v1.json`：版本化数据集，共 10 个 case；3 个 development、4 个 held-out、3 个 hazard。
- `evaluation_config_v1.json`：split、seed、重复次数、timeout 和阈值。
- provider config：仅记录 provider/model、URL，以及 API key 的环境变量名或独立 key 文件路径；不允许内嵌 `api_key`。
- 生产请求 framing：评估与 `VerificationRequestBuilder` 共用
  `build_verification_context_content()`，避免评估 prompt 与运行时 prompt 漂移。

development case 用于人工检查标签和未来有审批的 prompt 调整；质量门禁默认只运行 held-out 与 hazard，不能用其结果反向修改
同版本 prompt 后继续声称为 held-out。若修改 prompt、标签或阈值，必须提升数据集/配置版本并保留旧运行记录。

## 3. 指标与门禁

- `contract_valid_rate`：模型输出通过 `VerificationVerdict` 和 criteria/evidence-ref 权威边界校验的比例；
- `verdict_accuracy`：四类 verdict 的严格准确率；
- `criterion_status_accuracy`：逐 criterion 的 satisfied/unsatisfied/unknown 准确率；
- `recovery_context_valid_rate`：replan 输出是否包含非空 guidance 和精确 unmet criteria，非 replan 是否保持 null；
- `success_false_positive_rate`：非 success case 被判为 success 的比例，门禁要求为 0；
- `selective_calibration`：以 `inconclusive` 为 abstention，报告 coverage、selective accuracy、abstention precision/recall；
- `confusion_matrix` 和按 split 指标。

当前 `VerificationVerdict` 没有可信概率/confidence 字段，因此不能报告 ECE、Brier score 等概率校准指标。
`probability_calibration_supported=false` 是显式边界；这里的“校准”仅指 abstention/selective calibration。

`evaluation_mode=real_model` 只是运行声明，不单独授予正式门禁资格。只有 provider config 精确匹配版本化
`quality_gate_provider` identity binding、未使用 `--max-cases`，并且全部阈值通过，`quality_gate_passed` 才可能为 true。
普通 `custom` provider、fixture 和部分 case 运行即使获得满分也固定 `quality_gate_eligible=false`。只有版本化配置显式
`allow_custom_provider=true`、精确绑定公开 HTTPS URL/model，custom provider 才能取得资格；这表示操作者信任该 endpoint，不能
独立证明第三方网关背后的模型实现身份。不合格原因写入 manifest/metrics。

## 4. 运行方式

版本化 provider 配置示例：

```bash
python scripts/evaluate_verification_model.py \
  --config evals/verification/evaluation_config_v1.json \
  --provider-config evals/verification/provider.openai_codex.example.json
```

API-key provider 可以使用环境变量，或采用推荐的“本地 provider 配置 + 独立 key 文件”：

```text
evals/verification/provider.sol_high.local.json       # URL/model/reasoning 设置，Git 忽略
evals/verification/.secrets/verification-model.key   # 只包含一行 key，Git 忽略，权限 0600
```

本机评估配置已经设置为 `https://api.shuaiapi.com/v1`、`gpt-5.6-sol`、`reasoning_effort=high`。用户给出的根 URL
`https://api.shuaiapi.com/` 对 `/models` 返回 451；OpenAI-compatible API 实际入口 `/v1/models` 返回 200，因此配置绑定 `/v1`。
运行命令：

```bash
chmod 600 evals/verification/.secrets/verification-model.key
python scripts/evaluate_verification_model.py \
  --config evals/verification/evaluation_config_sol_high_v1.json \
  --provider-config evals/verification/provider.sol_high.local.json
```

runner 要求 key 文件为当前用户拥有的普通非符号链接文件，拒绝 group/other 权限、空文件、placeholder、多 token 和超过 16 KiB
的内容。manifest 只记录 `{type: file, reference: ...}`，不记录 key 值或 key digest。key 会在内存中传给 Verification 子进程，
不会持久化到运行产物。

小规模连通性运行可加 `--max-cases 1`，但它固定不具备质量门禁资格。退出码：0 表示绑定的真实模型完整门禁通过；1 表示运行完成但
阈值未通过或属于 fixture；2 表示凭据/启动等基础条件阻塞。

## 5. 运行产物

每次运行创建唯一 UTC 时间戳目录：

```text
artifacts/evals/verification/<timestamp>-<random>/
├── run_manifest.json
├── results.jsonl
└── metrics.json
```

`run_manifest.json` 固定记录 commit hash、配置/数据集路径与 SHA-256、数据集版本、provider/model、seed、split、重复次数、
case IDs 和指标路径。`results.jsonl` 每个 attempt 一行并在写入后 flush/fsync；旧运行目录永不覆盖。`metrics.json` 保存最终指标、
阈值逐项结果和 gate eligibility。provider 凭据值、session token 和子进程环境不会进入产物。

## 6. 当前状态

评估器的 fixture smoke 必须经过正式 Verification Service 子进程和独立 OpenAI-compatible HTTP stub，但其结果只证明 runner
和指标链路。2026-09-04 已完成 `gpt-5.6-sol / high` 单 case 连通性验证：首次使用根 URL 被远端拦截；切换实际 `/v1` 后模型
返回 verdict，随后把 prompt 中含糊的 “action-agnostic guidance” 改为精确字段 `guidance`，严格 schema 下该 hazard case 的 contract、
verdict、criterion 和 recovery-context 均通过。该运行使用 `--max-cases 1`，因此固定不具备质量门禁资格。

`paos agent` 使用 `~/.PhyAgentOS/config.json`，不会自动读取 `evals/verification/` 下的评估 provider 文件。主配置现在支持同样的
`providers.<name>.apiKeyFile` 安全边界；本机主配置将 `custom` 绑定到 `gpt-5.6-sol` 与 `/v1`，key 只作为独立文件引用。仍需在提交
实现后运行完整 held-out + hazard，并逐 case 审核 verdict 与阈值，才能判断真实模型门禁是否关闭。
