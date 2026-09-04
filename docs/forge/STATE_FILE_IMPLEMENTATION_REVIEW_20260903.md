# 状态文件适配实现审查与修复记录

日期：2026-09-03（Asia/Shanghai）
范围：`TARGETS.md`、`SESSIONS.md`、`ENVIRONMENT.md`、Evidence、Verifier、Verification Service，以及
`SKILLRUNTIME.md`/`LESSONS.md` 的边界。
原则：只接受真实生产 owner 的调用链证据；进程内 provider、Fake Store、回放数据只用于验证公开边界，
不构成 Gateway、Watchdog、Action、真实模型或硬件实现。

## 1. 原始审查发现

第一轮审查发现以下问题：

1. `AgentTaskStore` 的新字段迁移只增加了 `origin_dedup_key`，而写入路径同时要求
   `origin_session_key`，旧库会在初始化后首次写入时失败；origin 也没有在 `update()` 回调后保持不可变。
2. `SESSIONS.md` 编译器对任意异常都重新查询 origin 并当作幂等复用，可能把“任务已落库但后续绑定失败”误报为成功；
   文件数据根级未知字段也可能被忽略。`TARGETS.md` 还接受裸 scalar/array 限幅，且 baseline 未经过同一 schema 校验。
3. Evidence snapshot manifest 在 schema 校验前写入 artifact，非法 manifest 可能留下部分文件；Evidence 消费端只验证
   workspace 路径，未限定 bundle 所属的 writer-owned `evidence/` 目录。Bundle 与 AgentTask 的内容身份必须保持一致。
4. 未校验的 state-file 数据包含控制字符时可能进入 prompt；无效 `ENVIRONMENT.md` 的异常文本也可能把原始输入带入
   system prompt。环境 projection 不能成为 Evidence 或 verdict 的事实源。
5. Verification Service 的 parent/child provider 配置需要同一 strict schema；启动超时、请求体上限、URL/header
   校验和对外错误不能依赖静默 fallback 或内部异常文本。
6. 通用 `render_skillruntime_projection()`/`render_lessons_projection()` 没有生产调用者，而真实 Skill lessons projection
   来自 `experience.sqlite3`。继续把两个 generic renderer 暴露为“已实现模块”会制造第二份 Runtime/Experience 协议。
7. `AgentTaskStore.update()` 允许可变回调在提交前留下未重新验证的聚合内容；非法 task 字段可能污染 SQLite 权威事实。
8. robot-state artifact 使用默认 JSON 编解码时可接受 `NaN`/`Infinity`；`apply_retention()` 也缺少持久化 Bundle 重载和精确
   artifact 集合校验，且原先没有 AgentTask finalize 的生产调用者。

## 2. 修复结果

### 2.1 AgentTask / SESSIONS

- [修改] `PhyAgentOS/forge/task.py:L45-L56` 将冲突身份明确命名为 `origin_dedup_key`，保留旧属性作为兼容别名。
- [修改] `PhyAgentOS/forge/task.py:L233-L262` 绑定 state-file approval 的 source digest、declaration id 与两个 origin
  identity；不匹配时拒绝构造 `AgentTaskRecord`。
- [修改] `PhyAgentOS/forge/task.py:L291-L361` 新建表直接包含两个 origin 列；旧表可重入地分别迁移两个列，唯一索引只
  约束 `origin_dedup_key`，回填旧 `record_json` 中的非唯一 session 查询值，并增加非唯一 session 查询索引。
- [修改] `PhyAgentOS/forge/task.py:L381-L411,L417-L463` 在 `create()`/`update()` 中重建并验证完整聚合，比较更新前后的 task identity 与
  origin/session/approval，任何改变均回滚并
  抛出 `AgentTask origin is immutable`；提交前重新验证整个 `AgentTaskRecord`，非法可变回调不会落库。
- [修改] `PhyAgentOS/state_io/adapters.py:L432-L489` 拒绝 SESSIONS 数据根级未知字段和重复 acceptance criterion，默认
  verification mode 仍为 `enforce`。
- [修改] `PhyAgentOS/state_io/adapters.py:L275-L322` 限幅只接受 `{value}` 或 `{min,max}` 的严格联合结构；数组非空、
  长度相等、数值有限且 min 不得大于 max。
- [修改] `PhyAgentOS/state_io/adapters.py:L390-L405` promotion 前先用同一 validator 校验 baseline。
- [修改] `PhyAgentOS/state_io/adapters.py:L548-L550` 仅在捕获明确的 `AgentTaskOriginConflictError` 时进行并发复用；
  coordinator 创建后的其他异常不再被伪装成成功。

### 2.2 State protocol / ENVIRONMENT

- [修改] `PhyAgentOS/state_io/protocol.py:L31-L55,L106-L137,L140-L155` 对 JSON/YAML mapping key 与 state data 的递归字符串拒绝控制字符，同时保留 finite JSON 校验。
- [修改] `PhyAgentOS/agent/context.py:L187-L220` 只向 system prompt 注入严格 projection 的 bounded identity metadata，
  不注入 `scene_graph` 原文；解析失败只返回稳定的 `invalid_environment_projection` code，不回显异常详情。
- [修改] `PhyAgentOS/utils/helpers.py:L15-L27` 旧 `load_environment_doc()` 改为 deprecated 且 fail-closed，调用严格 parser，
  不再返回空字典掩盖损坏状态。
- [修改] `PhyAgentOS/state_io/__init__.py:L3-L54` 移除没有生产 owner 的 SKILLRUNTIME/LESSONS generic renderer 公共导出；
  通用 `write_projection()` 仍可供未来明确的 projection producer 使用。

### 2.3 Evidence / Verifier

- [修改] `PhyAgentOS/forge/evidence.py:L118-L152` 校验 session/namespace path safety；
  `L165-L244` 先构造并校验 v2 manifest，再预检所有不可变 artifact，最后写入，避免 schema 失败留下部分 artifact。
- [修改] `PhyAgentOS/forge/evidence.py:L247-L350` 严格校验 manifest version/phase、writer-owned 路径、sha256、byte size、
  media type、重复 image source、单一 robot state 和 JSON object payload。
- [修改] `PhyAgentOS/verification/contracts.py:L174-L207` 以 capture facts（含 version 和 gateway instance）派生稳定 Bundle
  identity，排除 retention tombstone 字段。
- [修改] `PhyAgentOS/verification/request_builder.py:L198-L227` 只加载 `artifacts/**/evidence_bundle.json`，校验 Bundle 内容
  identity 和 AgentTask 保存的 `evidence_bundle_id`；`L249-L285` 只消费同一 bundle 目录下的 writer-owned evidence artifact，
  并拒绝重复 artifact 路径和非标准 JSON 常量。
- [修改] `PhyAgentOS/verification/service.py:L33-L51,L341-L351,L423-L435` strict JSON 与 invalid provider response 对外只返回稳定 reason，详细 schema 异常只写日志。
- [修改] `PhyAgentOS/agent/session_verifier.py:L193-L275` retention 重新加载并验证磁盘 Bundle、绑定 request builder 已验真的
  artifact 集合和 owner 目录；`PhyAgentOS/forge/task.py:L1193-L1244` 仅在 AgentTask 终态调用 retention，失败记录 bounded event/error，
  recovery 中间态不提前删除证据。

### 2.4 Verification Service 配置与 HTTP

- [修改] `PhyAgentOS/verification/service.py:L56-L162` 增加 parent/child 共用的 `VerificationProviderSpec` 和
  `VerificationServiceSettings`：registry allowlist、provider-specific 必填项、绝对 HTTP(S) URL、端口、query/fragment、
  credentials、header control characters、duplicate normalized header、token、timeout、request-size 和 gateway/local endpoint 均 fail-closed。
- [修改] `PhyAgentOS/verification/service.py:L197-L239` parent constructor 在启动子进程前验证 host/port/secret/timeout/size/provider。
- [修改] `PhyAgentOS/verification/service.py:L372-L421` HTTP handler 验证 token、Content-Type、Content-Length、body 上限和严格
  request envelope；provider timeout/failure 对外分别为 `verification_provider_timeout`/`verification_provider_failed`。
- [修改] `PhyAgentOS/config/schema.py:L341-L361` 对配置层的 timeout、host、port、startup timeout 和 request-size 与 child schema 对齐。

## 3. 第二轮代码 review（已修复）

### 架构集成

通过。`state_io` 只解析/投影/调用公开 coordinator promotion，不拥有 Gateway、Watchdog、Action 或 Runtime queue。
`SESSIONS.md` 仍经 `AgentTaskCoordinator` 写入唯一 SQLite 生命周期事实源；TARGETS candidate 固定
`motion_authorized=false`；ENVIRONMENT 只作为 projection；Skill lessons 的机器事实仍来自 Experience ledger。

### 失败路径

通过。已覆盖 malformed/unknown/control-character state、可重入 SQLite migration、同 session 多任务、dedup 并发冲突、
origin mutation、非法 task mutation、manifest v1/tamper/size/digest/URI、非标准 robot-state JSON、Bundle drift、
AgentTask–Bundle mismatch、retention post-build mutation、invalid ENVIRONMENT、unknown provider、child unknown fields、
HTTP 400/403/413/415/500/504。失败不会静默创建半有效任务，也不会授权动作。

### 权威边界

通过。Markdown 不是生命周期事实；AgentTask、Gateway execution、Evidence artifacts、Runtime state 和
`experience.sqlite3` 保持各自 owner。ENVIRONMENT 不能作为 Evidence/verdict；Lesson 不能证明 criterion；provider
过滤或 verifier 成功不能产生 motion authorization。

### 配置

通过。provider registry 是 allowlist；parent 与 child 使用同一 Pydantic schema；host/port、startup timeout、provider timeout、
request bytes、temperature/max_tokens 和 provider-specific endpoint 均来自配置或受约束默认值；直接 handler 不再静默钳位非法
request-size，没有未知 provider fallback。

### 可维护性

通过。旧 environment loader 不再 fail-open；generic SKILLRUNTIME/LESSONS renderer 不再作为公共“完成模块”；SQLite migration
可重复执行；Store update、Evidence writer/consumer、retention 和 Service handler 都在权威边界重新验证；对外错误使用稳定 code；
测试 fixture 没有被接入生产调用链。

## 4. 第三轮代码 review

### 发现与修复

1. `AgentTaskStore.update()` 原先只重验字段 schema 和 origin，仍允许 mutation 改写 `task_id`，导致 SQLite 主键与
   `record_json.task_id` 分裂；同时 `create()` 接受已构造后被非法修改的 Pydantic 对象，可能把不可反序列化的记录写入权威库。
2. JSON/YAML state block 的默认 mapping loader 会静默接受重复 key，后出现的值可以覆盖已审核字段。
3. Verification Service HTTP handler 的 `json.loads` 默认接受 `NaN`/`Infinity`，非标准数值可能穿过请求边界；父进程构造器还会
   隐式强转 host、secret、port、timeout 和 request-size。
4. `ToolExecutionRecord` 的自由形态 execution payload 与 task event payload 若不做 finite JSON 校验，可能把非标准数值
   写入 SQLite，破坏 AgentTask 事实的可回放性。

### 修复结果

- [修改] `PhyAgentOS/forge/task.py`：`AgentTaskRecord` 增加 revision、active revision 和 execution lineage 关系校验；
  `AgentTaskStore.create()`/`update()` 均在事务提交前重建并验证完整聚合，`task_id`、`created_at` 与 origin identity 均不可变。
- [修改] `PhyAgentOS/state_io/protocol.py`：JSON `object_pairs_hook` 和唯一键 YAML loader 拒绝重复 mapping key。
- [修改] `PhyAgentOS/verification/service.py`：请求与响应 client 使用 strict JSON loader；父进程构造器拒绝隐式类型转换，
  只接受显式合法 host、secret、整数端口/请求上限和有限 numeric timeout。
- [修改] `PhyAgentOS/forge/task.py`：`ToolExecutionRecord.arguments/response/error` 和 task event payload 在 Store 边界拒绝
  非 finite JSON 值，避免 `NaN`/`Infinity` 污染 SQLite。
- [新增/修改] `tests/test_state_file_authority_boundaries.py`、`tests/test_state_file_adapter.py`、
  `tests/test_verification_service_replay.py`、`tests/test_verification_service_config.py`：通过真实 Store、协议解析器和
  HTTP handler 覆盖身份分裂、聚合关系、重复 key、非标准 JSON 和隐式配置类型失败路径。

### 第三轮结论

通过。生产写入与消费边界均 fail-closed；重复 key、非标准 JSON、非法聚合关系、非 finite execution/event payload 和隐式配置类型
不会进入权威事实或 provider。
未改变 Gateway、Watchdog、Action、Runtime admission 或硬件 owner；测试仍是边界证据，不等同于真实 provider 子进程或模型质量验收。

## 5. 验证证据与明确延后项

验证命令：

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -q tests
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=examples/forge-skills/pick-place-workflow/src python -m pytest -p pytest_asyncio.plugin -q examples/forge-skills/pick-place-workflow/tests
python -m ruff check PhyAgentOS tests/...
python -m compileall -q PhyAgentOS tests
git diff --check
```

结果：仓库测试 `127 passed`，pick-place 示例测试 `241 passed`；Ruff、compileall、diff check 通过。显式加载
`pytest_asyncio.plugin` 后没有 `asyncio_mode` 警告。直接运行未隔离的 `python -m pytest -q tests` 会在收集前被系统 ROS
`launch_testing` 插件的缺失依赖 `lark` 阻断；因此验证命令固定关闭第三方插件自动加载，再显式加载项目所需插件。

新增/修复测试使用真实 `AgentTaskStore`、`ForgeEvidenceWriter`、`VerificationRequestBuilder`、`ContextBuilder` 和 HTTP handler
公开边界；新增的 `test_verification_service_process.py` 进一步启动正式 `VerificationServiceProcess` 子进程，并通过外部
OpenAI-compatible HTTP stub 验证 provider-spec 传递、私有 readiness、鉴权请求、结构化 verdict、provider 失败、超时和 stop
清理。该 stub 不是进程内 provider，也不连接外部模型、Gateway、Watchdog 或 Action，没有硬件运动。

以下项目仍未实现，也不应由本轮测试推断为已实现：

- 真实模型的语义质量、校准和 held-out 评估；
- 真实 Gateway/Dora wiring 与抓取放置动作闭环；
- `SKILLRUNTIME.md` producer 和 Skill-scoped `LESSONS.md` 之外的第二套 projection 协议；
- TARGETS candidate 到 Runtime/Profile/Action admission 的授权接入。

兼容性说明：旧 `forge_observation_snapshot_v1` manifest 和没有内容派生 identity 的历史 Bundle 会明确 fail-closed，
不会被静默升级为可信 Evidence；尚未完成的旧任务需要重新捕获 Evidence。空 capture manifest 仍允许持久化，缺失 artifact
由 Bundle quality 标记为 incomplete，从而保留现有任务失败/诊断路径，而不是在 writer 层伪造观测。

因此，provider-spec 的真实生产子进程门禁已完成。下一步是人工审核本次门禁证据后，安排真实模型语义质量、校准和 held-out
评估；真实 Gateway/Dora wiring 与抓取放置闭环继续后置。文件适配完成不等于五个 Markdown 文件全部成为机器事实源，也不改变
PAOS 的自主进化边界。

## 9. v3.8.1 PAOS Agent 主配置凭据接入

`paos agent` 与 Verification 评估器读取不同配置入口：前者读取 `~/.PhyAgentOS/config.json`，后者读取
`evals/verification/evaluation_config_*.json` 与 provider config。此前只配置评估器文件会导致 Agent 启动时报
`No API key configured`，这不是 LiteLLM cost-map 代理警告导致的失败。

主配置的 `ProviderConfig` 现在支持 `apiKeyFile`。该字段只保存路径，不保存解析后的 key；运行时解析要求文件为当前用户所有的普通
非符号链接文件、权限不开放给 group/other、大小在 1..16 KiB、UTF-8 且恰好包含一个非空 token，并拒绝 placeholder。`apiKey`
与 `apiKeyFile` 同时出现会在 schema 层 fail-closed。相对路径以主配置文件所在目录为基准。

本机 `~/.PhyAgentOS/config.json` 已将 Agent 默认模型/provider/reasoning 设置为 `gpt-5.6-sol`、`custom`、`high`，API base 为
`https://api.shuaiapi.com/v1`，并只引用现有独立 key 文件；key 值没有进入配置、日志、Git 或运行产物。LiteLLM 的
`socks://127.0.0.1:7897` cost-map warning 可存在，但不是凭据配置错误。

### 验证

- `tests/test_config_api_key_file.py` → `3 passed`。
- 主配置解析与 provider 选择已通过本地无网络检查；未启动 Gateway、Dora、Action 或硬件。

## 6. v3.6.0 provider-spec 子进程门禁

### 实现与代码审查

- [修改] `PhyAgentOS/verification/service.py:L28,L282-L306,L403-L418`：增加稳定服务标识
  `paos-verification-service-v1`；父进程启动后使用带 session token 的 `/readyz` 私有探针，严格校验 JSON 响应和服务标识，
  不再把任意占用端口且返回 `/healthz=200` 的 HTTP 服务误认成子进程；保留 `/healthz` 作为公开 liveness。
- [新增] `tests/test_verification_service_process.py:L1-L239`：启动正式 `python -m PhyAgentOS.verification.service` 子进程，
  通过独立 OpenAI-compatible HTTP stub 验证 provider-spec 的 model/api key/api base/temperature/max_tokens 传递、请求消息、
  结构化 verdict、provider 失败映射为稳定 HTTP 500、超时映射为 HTTP 504、私有 readiness 鉴权和进程 stop 清理。

### 代码审查结论

通过。生产 owner 仍是 `VerificationServiceProcess`；测试 stub 只扮演外部 provider，不创建第二套 Verification 协议，不改变
Gateway、Watchdog、Action、Evidence 或硬件 owner。readiness 现在同时绑定 session token 和服务标识，失败路径保持 fail-closed。

### 验证

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -q tests/test_verification_service_process.py tests/test_verification_service_config.py tests/test_verification_service_replay.py` → `42 passed`。
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -q tests` → `127 passed`。
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=examples/forge-skills/pick-place-workflow/src python -m pytest -p pytest_asyncio.plugin -q examples/forge-skills/pick-place-workflow/tests` → `241 passed`。
- `python -m ruff check PhyAgentOS/verification/service.py tests/test_verification_service_process.py`、`python -m compileall -q PhyAgentOS/verification/service.py tests/test_verification_service_process.py`、`git diff --check` → 通过。

### 明确未完成

- 真实模型语义质量、校准和 held-out 评估；
- 真实 Gateway/Dora wiring、完整 Action executor 和抓取放置闭环；
- `TARGETS` candidate 到 Runtime/Profile/Action admission 的生产授权接入。

## 7. v3.7.0 真实模型语义评估基础设施（历史快照）

### 实现与审查修复

- [新增] `PhyAgentOS/verification/evaluation.py`：严格加载版本化 dataset/config/provider config；按 seed 选择 split，创建唯一 UTC
  运行目录，经正式 `VerificationServiceProcess` 执行每个 case，逐条 fsync 结果，并持久化 commit、配置/数据集 digest、model、
  checkpoint identity、超参数、原始 verdict、分 split 指标和阈值结果。凭据只通过环境变量名引用，不进入产物。
- [新增] `PhyAgentOS/verification/validation.py`，并修改 `agent/session_verifier.py`：将 criteria identity 和 evidence-ref 权威校验
  从 Agent 层下沉到 Verification 公共边界，避免评估模块反向依赖 Agent；`ForgeTaskVerifier` 保持原有错误契约。
- [修改] `PhyAgentOS/verification/request_builder.py`：生产 request 和评估 runner 共用
  `build_verification_context_content()`，避免语义评估 prompt framing 漂移。
- [新增] `evals/verification/semantic_verifier_v1.json` 与 `evaluation_config_v1.json`：10 个版本化 case，development/held-out/hazard
  分离；默认门禁只运行 4 个 held-out 和 3 个 hazard case。
- [新增] `scripts/evaluate_verification_model.py` 与 `tests/test_verification_model_evaluation.py`：提供 CLI、正式子进程 fixture smoke、
  缺凭据 blocker、唯一目录、脱敏元数据、重复 key 拒绝和启动错误终态测试。

代码审查发现并关闭两个 Major：评估模块原先反向依赖 Agent 层；子进程启动异常可能把 manifest 留在 `running`。当前通用校验已
下沉，启动异常会写入 terminal `error` manifest/metrics。fixture 即使指标满分也固定
`quality_gate_eligible=false`，不能冒充真实模型门禁。

### 指标边界

评估报告 contract validity、verdict/criterion accuracy、recovery-context validity、非 success 的 success false-positive rate、
confusion matrix，以及把 `inconclusive` 当作 abstention 的 coverage/selective accuracy/abstention precision/recall。当前 verdict
没有概率 confidence，因此明确记录 `probability_calibration_supported=false`，不伪造 ECE 或 Brier score。

代码审查进一步关闭了两个门禁资格漏洞：`evaluation_mode=real_model` 仅是声明，运行还必须精确匹配版本化
`quality_gate_provider` identity binding；`custom` endpoint 与 `--max-cases` 部分运行无论分数如何都不能成为正式质量证据。

### 当前运行证据

fixture runner smoke 已通过正式 Verification Service 子进程，但仅作为实现测试。以下是 v3.7.0 时点的历史快照；当时的真实模型预检运行写入
`artifacts/evals/verification/20260903T163926.458050Z-db095983/`，状态为 `blocked`，并记录实现提交
`8775073eccb26791a5ffd0215794c49fd46f3f82`：当前没有 PAOS provider API key，现有
Codex OAuth 也不能由 `oauth-cli-kit` 读取。该运行没有模型请求、没有质量分数，`quality_gate_eligible=false`。

因此，v3.7.0 时点的真实模型语义质量门禁尚未关闭。该 blocker 已在 v3.8.0 通过独立 key 文件和第三方
OpenAI-compatible endpoint 的单 case 连通性验证中解除；完整 held-out + hazard 质量门禁仍未运行，Gateway/Dora 和抓取放置闭环继续后置。

## 8. v3.8.0 API-key 文件接入与 sol/high 连通性

用户选择配置文件接入并提供第三方 OpenAI-compatible URL/key。实现新增 `api_key_file`，相对路径以 provider config 所在目录为
基准；key 文件通过 `O_NOFOLLOW` 打开，必须属于当前用户、为普通文件且不授予 group/other 权限。provider config 与 key 文件分别
由 `.gitignore` 隔离，运行产物只记录安全的 source type/reference，不记录 key 或 digest。

版本化 `evaluation_config_sol_high_v1.json` 显式绑定 `custom + gpt-5.6-sol + https://api.shuaiapi.com/v1`，并以
`allow_custom_provider=true` 表达人工信任边界。该绑定可以阻止本地 fixture 或其他 URL/model 冒充本次门禁，但不能独立证明第三方
网关实际后端模型身份。provider 本地设置为 `reasoning_effort=high`、`temperature=0`、`max_tokens=4096`。

网络探测显示用户给出的根 URL 的 `/models` 返回 451，而 `/v1/models` 返回 200。修正到 `/v1` 后真实模型首次返回的
`recovery_context` 将 prompt 中 “action-agnostic guidance” 误作字段名，被严格 `extra=forbid` 拒绝；生产 prompt 已改为明确要求
`unmet_criteria`、`preserved_constraints`、`guidance` 三个字段，未放宽 schema。再次运行同一 hazard case 后 contract、verdict、
criterion 与 recovery-context 指标均为 1.0，且无凭据泄漏。因为使用 `--max-cases 1`，该证据只证明连通性和契约可用，不能关闭门禁。

该历史记录之后，完整 held-out + hazard 评估已在 v3.8.3 完成；详见下方最新审计记录。

## 10. v3.8.3 完整真实模型语义质量门禁

运行目录：`artifacts/evals/verification/20260904T034715.434600Z-42a21625/`。

- manifest 绑定完整提交 `2722d78d1f21d43f12c0213811376ee8f8bf57a8`、数据集版本 `1.0.0`、7 个 held-out/hazard case、
  `custom` provider、模型 `gpt-5.6-sol`、`https://api.shuaiapi.com/v1`、`reasoning_effort=high`，并记录 file credential source
  的引用而非 key 值。
- `quality_gate_eligible=true`、`quality_gate_passed=true`；总体 contract validity、criterion accuracy、recovery-context
  validity 均为 `1.0`，`success_false_positive_rate=0`，verdict accuracy `0.8571428571428571`，阈值逐项通过。
- 逐 case 审核确认 7 条结果均为合法结构化 verdict，evidence refs 未越权，未发现凭据/Bearer 泄漏。唯一语义误差是
  `held_replan_execution_success_world_failure`：期望 `replan_required`，实际为 `inconclusive`；held-out accuracy 为 `0.75`，
  仍高于配置的总体门槛 `0.8`，但构成后续 replan/inconclusive 质量改进项。

本次门禁可以关闭 Verification 语义质量 gate，但不能推导出 Gateway/Dora、Action executor、抓取放置或硬件运动已经实现。
按照已批准执行顺序，下一步是 Gateway/Dora 的无动作 wiring、身份/超时/失败 conformance 和代码审查；该阶段通过后才进入抓取放置
闭环，之后才讨论基于执行证据的受控自主进化。

## 11. v3.9.0 Gateway/Dora 无动作 wiring 与五维验收

本阶段的“之前五个模块”指五个验收维度，而不是五个 Markdown 状态文件：架构集成、失败路径、权威边界、配置、可维护性。
实现保持 provider-neutral、dry-run/no-motion；没有连接真实 Dora、Gateway、Action 或硬件。

### 实现与代码审查结论

- [架构集成] `CapabilityRuntimeTransport` 位于 `PhyAgentOS/forge/capability_runtime`，复用既有 `CapabilityRuntime` 和 `ForgeToolClient` 协议，提供 `/tools`、context、Query、Action/Session invocation、status/result、cancel/stop 路由；不创建第二套执行平面。
- [失败路径] Runtime deadline 到期明确变为 `unknown`；cancel/stop 先记录 request，再在 status/result reconciliation 中变为 terminal `cancelled`/`stopped`；malformed JSON 返回 400 `invalid_json`，不创建 invocation；pending/unknown 的重复读取不发送 POST。
- [权威边界] Gateway identity 由 transport discovery 返回并由 Runtime/Binding 继续持有；`invocation_id`、`attempt_id`、`caller_id` 由 Runtime 生成/关联；adapter 不生成伪造 result，也不授予 motion authorization。
- [配置] gateway identity 为构造参数且严格要求非空；timeout 仅接受正整数，Session 明确拒绝 timeout；未引入 URL、凭据、Dora 或硬件硬编码。
- [可维护性] HTTP adapter 是可复用正式模块，测试只验证该模块，不把 example FakeGateway 作为生产实现；错误映射、终态集合和 no-motion 约束均有直接回归覆盖。

### 验收结果

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -q tests/test_gateway_dora_no_motion_conformance.py examples/forge-skills/pick-place-workflow/tests/test_generic_capability_runtime.py` → `11 passed`。
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -q tests` → `150 passed`。
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=examples/forge-skills/pick-place-workflow/src python -m pytest -p pytest_asyncio.plugin -q examples/forge-skills/pick-place-workflow/tests` → `243 passed`。
- `python -m ruff check PhyAgentOS/forge/capability_runtime tests/test_gateway_dora_no_motion_conformance.py`、`python -m compileall -q PhyAgentOS tests`、`git diff --check` → 通过。

该阶段通过五维验收，但仍不等同于真实 Dora/Gateway 进程互操作、Action executor、抓取放置闭环或硬件安全证明；这些保持后置。

## 12. v3.10.0 抓取放置证据闭环与五维复审

本阶段实现聚焦 provider-neutral `grasp.propose → manipulation.prepare → object.acquire → object.place` 的闭环投影，继续保持 dry-run/no-motion；没有连接真实机器人或硬件。

### 实现与代码审查结论

- [架构集成] `LongHorizonWorkflow.record_terminal_response()` 直接消费标准 Gateway terminal response，复用既有六步 reducer，不新增 Gateway、Session 或 Markdown 执行平面。
- [失败路径] blocked/failed/cancelled/unknown 继续停止自动推进；recovery 只能创建新 revision；terminal place 缺少完整 post-release evidence 或 acquire identity 不一致时 fail-closed。
- [权威边界] observation、candidate-set、preparation、acquire invocation、place invocation 和 post-release artifact 均通过显式引用关联；workflow 仅保留 opaque refs，不承载坐标、provider payload 或物理真值。
- [配置] destination 使用严格 `destination://` schema；新增入口不引入 URL、凭据、Dora、设备或控制器硬编码。
- [可维护性] terminal-response adapter 消除手工 refs 拼接；测试覆盖完整链路、跨场景漂移、恢复、acquire/place 绑定和 post-release evidence 缺失。

### 验收结果

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -q tests` → `151 passed`。
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=examples/forge-skills/pick-place-workflow/src python -m pytest -p pytest_asyncio.plugin -q examples/forge-skills/pick-place-workflow/tests` → `245 passed`。
- `python -m ruff check PhyAgentOS tests examples/forge-skills/pick-place-workflow/src examples/forge-skills/pick-place-workflow/tests`、`python -m compileall -q PhyAgentOS tests examples/forge-skills/pick-place-workflow/src`、`git diff --check` → 通过。

五维复审无 Blocker/Major 遗留。该结果证明抓取放置的协议级证据闭环，不证明真实 Action executor、Dora/机器人互操作、物理成功或自主进化 promotion。

## 13. EnvironmentAdapter / provider-neutral observation seam

本阶段按既定顺序进入 EnvironmentAdapter 接入门禁，范围限定为 reset/snapshot 与无动作
`scene.observe` Query。实现没有启动真实机器人、Dora、Action executor 或硬件，也没有把 RoboTwin
actor/entity truth 写入公共 observation。

### 实现结果

- [架构集成] `ObservationEndpoint` 位于核心 capability runtime，通过注入的 `ObservationSource.capture()`
  接收测量结果；`OBSERVATION_TOOL_SPEC` 与其他 generic ToolSpec 一样必须由调用方显式注册到
  `CapabilityRuntime`，transport 不隐式创建环境依赖。RoboTwin20 adapter 只负责 profile、reset、snapshot
  和 camera/depth/state artifact 投影。
- [失败路径] 输入在 source 调用前校验；provider exception、`None`、`sensor_available=false`、缺失 revision/frame/
  calibration/artifact、重复或 actor-like artifact、错误 observation binding、非法 timestamp、requested frame
  不匹配和 stale observation 均 fail-closed。provider 详情不会回显，错误使用稳定 code；错误时间戳使用注入 clock。
- [权威边界] endpoint 只投影 observation identity、revision、frame、calibration、freshness 与 artifact refs；不创建
  AgentTask、Evidence、verdict、entity truth、candidate 或 action admission。RoboTwin backend 的 snapshot 仅返回 profile/
  revision/status，ObservationSource 不转发 actors、segmentation 或内部 pose。
- [配置] sensor refs、profile 名称、runtime/artifact 根目录和 calibration 由 adapter/profile/backend 提供；核心
  ToolSpec 不含 RoboTwin、SAPIEN、模型、设备或路径。环境差异不会进入 Skill 或第二份配置源。
- [可维护性] public schema 与 endpoint validator 同处一个 owner；错误投影、时钟和 provider port 可注入测试；显式
  registration 避免重复 wiring。RoboTwin adapter 继续保持独立 package，PAOS 不依赖可选仿真/视觉库。

### 验证与边界

- `tests/test_environment_adapter_observation.py` → `10 passed`，覆盖成功投影、freshness、provider failure、sensor
  unavailable、binding/artifact/calibration/timestamp/输入失败以及显式 runtime registration。
- 根仓库测试 → `161 passed`；RoboTwin adapter 无第三方依赖子集 → `16 passed`；Ruff、compileall、`git diff --check` 通过。
- RoboTwin adapter 完整测试仍受当前 PAOS 环境缺少 `numpy` 与 `pick_place_workflow` 路径影响，不能宣称完整 adapter
  runtime 已验收；真实传感器、跨进程 Gateway/Dora、模型语义质量和硬件运动仍未完成。

### 五维结论

EnvironmentAdapter / observation seam 五维审查通过，无 Blocker/Major。该结论只表示核心 Query contract、adapter
port 和 no-motion replay 边界已具备；下一步应按顺序审查并实现 `scene.understand` 对正式 observation/geometry artifact
的消费，再进入真实 Gateway/Dora provider wiring。不得把本阶段结果表述为真实环境或抓取放置完成。

## 14. scene.understand observation/artifact consumer hardening

本阶段继续按执行顺序完善 `scene.understand` 对正式 `scene.observe` 输出的消费，仍为 provider-neutral Query、无动作、无
真实 Gateway/Dora/硬件连接。

### 代码审查发现与修复

- [架构集成] `SceneUnderstandingEndpoint` 现在只使用与 observation 请求严格绑定的 revision/frame/calibration/artifact
  identity；provider 收到深拷贝请求，不能通过原地修改请求改变后续绑定校验。
- [失败路径] `observation_ref` 必须等于 `observation://{scene_revision}/{frame_id}`；请求 artifact refs 必须有效且不重复；
  entity/relation/spatial provenance 必须非空、唯一并属于输入 artifact；spatial envelope frame 必须等于 observation frame。
- [权威边界] provider 仍只能返回 entity/relation/geometry claim 与 opaque derived artifact，不能携带 provider-specific
  字段；所有派生 artifact 必须绑定当前 observation 并通过 lineage 校验。
- [配置] 未增加模型、设备、URL 或仿真器配置；provider 仍通过 adapter port 注入，公共 ToolSpec 未变化。
- [可维护性] 删除重复错误字段，统一使用显式稳定错误码；新增验证覆盖 identity、重复 refs、provenance、frame drift 和
  provider request mutation。

### 验证与结论

- `test_scene_understand.py` → `21 passed`；根仓库 → `161 passed`；pick-place 全量 → `250 passed`。
- RoboTwin scene-understand/single-view provider → `7 passed, 1 skipped`（命令显式加入 adapter 与 pick-place 两个 source
  root）；Ruff、compileall、`git diff --check` 通过。
- 五维复审无 Blocker/Major。该阶段证明 observation→understanding 的协议绑定和 no-motion 边界，不证明真实模型语义质量、
  GraspGen live、Gateway/Dora 互操作或物理执行。

## 15. grasp.propose geometry-artifact consumer hardening

本阶段按执行顺序让 `grasp.propose` 消费 `scene.understand` 产生的正式 geometry artifact，继续保持 provider-neutral
Query、dry-run/no-motion；没有执行 IK、碰撞准入、Action、Dora 或硬件运动。

### 五维代码审查结论

- [架构集成] `GraspProposalEndpoint` 位于核心 capability runtime；target 的 `geometry_artifacts` 只允许 observation-bound
  `object_point_cloud`/`fused_entity_perception`，adapter-side provider 通过 `PointCloudArtifactResolver` 与独立 worker
  port 消费，不把模型实现带入 PAOS。
- [失败路径] observation_ref 必须匹配 revision/frame；target 与 geometry artifact 的 entity/revision/frame/calibration
  必须一致；artifact refs 和 candidate provenance 必须非空、唯一并绑定输入 provenance；provider 异常、不可用、invalid
  snapshot、stale/empty 与 cleanup 失败均 fail-closed，不伪造候选。
- [权威边界] Endpoint 只投影 candidate-set、candidate refs、姿态候选和 provenance，不执行 IK、碰撞、workspace 或 motion
  admission；provider 接收深拷贝请求，不能改变公共 binding。
- [配置] worker、模型 variant、artifact root、阈值、NMS 和 collision-filter flag 仍由 adapter/profile 注入；核心
  contract 未增加 RoboTwin、GraspGen、设备、路径或凭据字段。
- [可维护性] provenance validator 统一处理非空/唯一引用；`allowed_provenance` 提供兼容默认值，避免破坏
  `manipulation.prepare` 复用的内部 candidate validator。

### 验证与边界

- `test_grasp_propose.py` → `61 passed`；根仓库 → `161 passed`；pick-place 全量 → `253 passed`。
- adapter GraspGen 专项无法在当前 PAOS 环境收集，原因是缺少可选 `numpy`；因此不宣称 verified checkpoint live inference
  或完整 adapter GraspGen 验收。Ruff、compileall、`git diff --check` 通过。
- 五维复审无 Blocker/Major。下一步是独立 adapter geometry consumer 证据，再进入 `manipulation.prepare` 正式消费；本阶段
  不等同于抓取位姿可执行或抓取成功。

## 16. manipulation.prepare candidate consumer hardening

本阶段按既定执行顺序进入 `manipulation.prepare` 的正式 candidate consumer。范围仍是 provider-neutral Query、dry-run/no-motion；
没有连接真实 Hephaestus executor、IK/碰撞引擎、Gateway、Dora、Action 或硬件。

### 五维代码审查结论

- [架构集成] `ManipulationPreparationEndpoint` 位于核心 capability runtime，复用 `grasp.propose` 的 candidate validator；`PreparationProvider` 通过注入的 `ReadinessEvaluator` 边界提供结果，不创建第二套执行平面。
- [失败路径] `observation_ref` 必须精确匹配 revision/frame，`candidate_set_ref` 同样绑定当前 revision/frame；重复 prepared candidate、候选实体漂移、非法 check/evidence、provider exception/unavailable/invalid snapshot、stale observation 均 fail-closed。
- [权威边界] 三项 readiness check（kinematic/collision/workspace）必须全部为 `pass` 才能投影 prepared candidate；endpoint 固定返回 `motion_authorized=false`，不创建 Action invocation，也不把 provider 结果升级为物理真值。
- [配置] 核心 runtime 不包含模型、设备、URL、凭据或 Hephaestus 路径；未来 IK、碰撞和 workspace 能力由 adapter/profile 注入 `PreparationProvider`。
- [可维护性] provider 请求使用 `deepcopy` 隔离，避免原地修改公共 binding；错误码、schema 与 validator 位于同一 owner，candidate validator 提供兼容默认参数。

### 验证与边界

- `test_manipulation_prepare.py` → `60 passed`；根仓库 → `161 passed`；pick-place 全量 → `256 passed`。
- `python -m ruff check ...`、`python -m compileall -q ...`、`git diff --check` 均通过。
- 本阶段只证明 candidate → readiness 的协议闭环和 no-motion 边界；不证明真实 IK、碰撞、轨迹可执行、物理可达、抓取成功或真实 Dora/Gateway 互操作。

### Hephaestus 参考边界

本阶段没有把 Hephaestus 源码作为 PAOS 运行时依赖接入，也没有复制其 executor、receipt、state store、ToolRegistry、CLI execution path 或 provider-specific payload。仅以 Hephaestus 已验证的行为语义作为 clean-room 参考：执行前准入、失败族显式化、证据绑定和动作默认拒绝。后续若接入真实 adapter，仍须通过 PAOS 自有 profile/runtime/action admission 与独立 no-motion 证据。

下一步是独立 adapter `ReadinessEvaluator` 的证据与 conformance；其后才可讨论真实 Gateway/Dora wiring 或物理 Action。自主进化 promotion 继续后置，必须依赖可归因、独立评估的执行证据。

## 17. RoboTwin20 adapter ReadinessEvaluator conformance

本阶段完成独立 `robotwin20_adapter.RoboTwinReadinessEvaluator`。它只接收冻结的 provider-neutral
`manipulation.prepare` request，验证 observation/candidate-set identity 与 candidate/entity 绑定，调用注入的
no-motion evaluator，并输出 prepared candidates、三项通过的 readiness checks 和 opaque evidence。PAOS endpoint 新增
mapping normalization，以便 adapter 不依赖 PAOS dataclass。

五维复审结论：架构上 evaluator 位于独立 adapter，PAOS 仍拥有最终 schema/动作边界；失败路径覆盖 provider 异常、
unknown/fail check、重复/越权 candidate、非法 evidence、provider-specific 字段和 identity 漂移并全部 fail-closed；
权威边界保持 `motion_authorized=false`，不创建 Action；配置通过注入 evaluator/profile 承载，不硬编码模型、URL、设备
或 Hephaestus 路径；可维护性通过 strict projection、deep-copy request 和 mapping normalization 保持跨进程兼容。

验证：adapter readiness 专项 `14 passed`；PAOS manipulation.prepare 专项 `60 passed`；根仓库 `161 passed`；pick-place
全量 `256 passed`；Ruff、compileall、`git diff --check` 均通过。该结果只证明 adapter→PAOS readiness evidence conformance，
不证明真实 IK、碰撞、轨迹、物理可达性、Action/Gateway/Dora 或硬件执行。Hephaestus 仍仅作为 clean-room 语义参考，未作为
运行时依赖接入。

完整 RoboTwin20 adapter 集合仍无法在当前 PAOS 环境收集依赖 NumPy 的 GraspGen/数值感知测试；该可选依赖缺失单独记录，
不影响本阶段 readiness conformance 的无第三方依赖验证。

下一步仍是对真实/独立 readiness worker 的 evidence 进行受控 no-motion 适配验证；只有该证据稳定后，才可讨论真实 Action/Gateway
wiring，之后才是物理执行和执行证据驱动的自主进化 promotion。

## 18. Readiness evidence replay worker conformance

本阶段完成独立 JSONL readiness replay worker 与 profile wiring。`readiness_replay_worker.py` 只读取外部 hash-pinned
fixture 和 evidence manifest，根据完整 observation/candidate identity 返回 prepared evidence；manifest 对每个 evidence
reference 绑定 observation、scene revision、frame、calibration、source 和带时区 capture timestamp。`ReadinessReplayClient`
校验 request identity、worker identity、replay schema 和 no-motion 标志后，才投影为 `RoboTwinReadinessEvaluator` 的
provider mapping。fixture/manifest 要求绝对 regular file、不可被 group/world 写入，并通过 SHA-256 校验；重复 case、未知
case、缺失/漂移 evidence、malformed fixture 和 worker 启动/响应失败均拒绝。

五维复审无 Blocker/Major：架构上复用既有 `JsonlProcessWorkerClient`，不创建第二执行平面；失败路径覆盖 startup、timeout/
shutdown、request/response identity、digest、路径、fixture/manifest schema、evidence binding 和 timezone；权威边界保持
PAOS 最终 projection 与 `motion_authorized=false`；配置通过 `readiness-replay.yaml` 外部变量和 profile 注入；可维护性通过
统一 worker lifecycle、严格 schema 和独立 replay client 保持清晰。回放证据明确不是真实 IK、碰撞、轨迹或物理成功证明。

验证：readiness/replay/process 专项 `34 passed`；依赖隔离 adapter 子集 `44 passed`；根仓库 `161 passed`；pick-place 全量
`256 passed`；Ruff、compileall、`git diff --check` 均通过。完整 RoboTwin20 adapter 集合仍受当前环境缺少可选 `numpy` 且
未注入 pick-place 源路径影响，未宣称 GraspGen/数值感知 live 验收。Hephaestus 仍仅作 clean-room 参考，未作为运行时依赖接入。

下一步是对真实或经独立验证的 readiness worker 产生 evidence replay；在该证据完成人工审核前，不进入真实 Action/Gateway
wiring 或硬件执行。为支撑这一门禁，adapter 现在可将已通过 worker conformance 的 no-motion projection 固化为不可变
canonical replay artifact，并绑定 fixture/manifest/request/result digest。该 artifact 仅用于 adapter-local 审计与回放，
不冒充 PAOS EvidenceBundle、Verifier 物理成功判断或 Action admission；fixture replay 仍不等价于真实 IK/碰撞/轨迹证据。

### 2026-09-04 自审结论与本体替换适配

按架构集成、失败路径、权威边界、配置、可维护性五个维度复核后，确认
PAOS 上层设置无需改为 RoboTwin 专属接口。需要修正的是 adapter-owned
profile：preflight/backend 支持原生双臂和双单臂 pair 语法，并在 setup 前
校验 `dual_arm` 拓扑；readiness replay 的 fixture、manifest、worker 和
artifact 统一校验 robot/gripper/topology/planner/profile digest 绑定。

本体替换因此只需替换 benchmark profile、embodiment config、planner 和
readiness binding，不复制 Skill、ToolSpec、AgentTask 或生命周期事实。新增
`franka-blocks-ranking.yaml` 作为首个长程场景（`blocks_ranking_rgb`），
仍保持 no-motion。执行顺序修订为：Franka observation → 独立 readiness
evidence + 人工审核 → Action/Gateway no-motion wiring → RoboTwin motion
simulation → 后续 benchmark 与受控自主进化。

## 19. 已接入 provider 的真实 no-motion 链路验收

按架构集成、失败路径、权威边界、配置、可维护性五个维度自审，无 Blocker/Major；当前门禁仍是“真实/独立 readiness
evidence → 人工审核 → Action/Gateway wiring”。

真实 run：`/home/yanxu/robotwin20-runtime/artifacts/paos-real-chain-20260905T0020Z/`，绑定 RoboTwin
`beat_block_hammer/demo_clean`、seed `0`、`aloha-agilex`，RoboTwin commit `3095469`；preflight 全部通过。
真实 `scene.observe` 产出 RGB/depth/state/calibration；`gpt-5.6-sol` 产出 4 entities/3 ambiguities；LocateAnything、
SAM2 和 RGB-D localization 产出 12 个派生 artifact。每阶段输入、输出、原始 stdout/stderr、profile digest 和 artifact
SHA-256 记录在 `run_manifest.json`，manifest digest 为 `da7a81bd2efccbf70312428a3adeef10babe2d465734f63f7c90444297389b46`。

GraspGen 因缺少 `GRASPGEN_PYTHON` 配置、readiness replay 因缺少 `READINESS_FIXTURE` 配置而 unavailable；`object.acquire`/
`object.place` 未尝试。所有 motion flags 均为 false。结论是 observation→understanding→single-view perception 的真实
no-motion 链路已验证，但不等于真实抓取位姿、IK/碰撞 readiness、Action executor、Gateway/Dora 或仿真动作成功。

## 20. GraspGen live provider seam review

外部 GraspGen workspace 已通过 profile 环境变量接入 adapter；首次跨进程验证发现第三方 logger 写入 stdout，修复后 worker
stdout 严格保持 JSONL，模型日志进入 stderr。对真实 RoboTwin `entity://red-rectangular-block-1` 点云执行
`GraspGenProposalProvider` no-motion `grasp.propose` 成功，返回 24 个 provider-neutral candidates，funnel `24/24/24/24`。

证据保存于 `/home/yanxu/robotwin20-runtime/artifacts/paos-graspgen-live-20260905T0040Z/`，manifest digest 为
`a7627a6d8583bf4da502dfe1deaf8c3ec1e978f8f274ede545446614f43ae336`。所有 motion flags 为 false；未调用 IK、碰撞、Action、
Gateway、Dora 或硬件。该阶段通过后仍只能进入 readiness worker evidence，不能直接进入 Action/Gateway wiring。
