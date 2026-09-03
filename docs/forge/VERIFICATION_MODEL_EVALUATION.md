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
- provider config：仅记录 provider/model 和 API key 的环境变量名，不允许内嵌 `api_key`。
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
`custom` provider、fixture 和部分 case 运行即使获得满分也固定 `quality_gate_eligible=false`；不合格原因写入 manifest/metrics。

## 4. 运行方式

OpenAI Codex OAuth 示例：

```bash
python scripts/evaluate_verification_model.py \
  --config evals/verification/evaluation_config_v1.json \
  --provider-config evals/verification/provider.openai_codex.example.json
```

API-key provider 应复制 provider config 到本地未提交文件，把 `api_key_env` 设置为环境变量名，然后在 shell 中设置该变量。
runner 不读取或持久化 key 值。

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
和指标链路。2026-09-03 当前机器没有 PAOS provider config/API key，且现有 Codex OAuth 不能被 `oauth-cli-kit` 读取；因此真实模型
质量结果仍是 blocked，不能以 fixture 分数替代。凭据可用后需运行完整 held-out + hazard 配置，并审核逐 case verdict 后才关闭该门禁。
