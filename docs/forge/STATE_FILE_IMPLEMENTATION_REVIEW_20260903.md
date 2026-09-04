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
