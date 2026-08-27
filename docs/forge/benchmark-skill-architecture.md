# Benchmark 类 Skill 目标架构:paos-gateway-policy_runner-benchmark(kai0-libero 适配)

> 状态:本文档为**目标契约文档**,记录 benchmark 类 Skill 应该具有的架构。
> 实现状态表见 §10;正文以目标形态描述,未实现项在状态表中标注。
> 本文档不描述构建/发布的具体操作步骤,操作规范以现有技能开发与发布文档为准。

## 1. 背景与目标

kai0-libero 是「跑 LIBERO 仿真基准」的典型 benchmark 类 Skill。其旧形态由四个节点与
约 780 行手写 wire adapter 组成:adapter 负责把 Tool 请求翻译成批次子流程,批次以子进程
dora run 启动,推理服务(openpi serve_policy)则完全游离在技能生命周期之外,由部署脚本
手工拉起、手工清理。

目标形态收敛为 **paos-gateway-policy_runner-benchmark** 三节点单流程:

- **gateway** — 控制面枢纽。HTTP 侧的 Tool invoke/status/result/cancel/stop 与
  forge_tool endpoint 协议在此汇合,语义分发(Query/Action/Session)与并发/租约管理
  全部内聚。
- **policy_runner** — 推理服务的常驻生命周期所有者,注册为 **Session tool**
  (attach-or-launch + 三段就绪门 + stop 释放 GPU)。
- **benchmark** — 仿真基准的执行者,注册为 **Action tool**(校验 → 进程内批次执行 →
  进度事件 → 七字段终态结果,cancel 给部分结果)。

本轮适配性结论:

- benchmark 用 Action 语义表达是**天然成立**的:单次批次是一次有界的、可取消的、
  有明确终态结果的执行,这正是 Action 的契约;本轮只需把既有批次执行逻辑包进
  ActionToolEndpoint,并把批次流程从子 flow 收回进程内。
- policy_runner 用 Session 语义表达**要求全链新能力**:session 在 forge 协议层、
  网关层两端此前均未实现(handler 对 session dispatch 抛 NotImplementedError,
  gateway 目录拒绝 session 注册)。本轮补齐两端后,推理服务生命周期被纳入 Tool
  生命周期,openpi 不再是无主的旁路进程。
- 节点单独落库:benchmark 与 policy_runner 的代码、构建、测试归属各自节点仓库,
  Skill 只保留锁与配置文件;最终交付物只有 skill bundle(含大模型权重)。

## 2. 总体架构

```
                        ┌─────────────────────────────┐
   上游 agent(HTTP) ───►│  gateway(控制面)             │
   invoke/status/result/│  ├─ 语义分发 query/action/   │
   cancel/stop          │  │   session                 │
                        │  ├─ ToolSpec/目录/租约       │
                        │  ├─ 并发与 deadline 管理     │
                        │  └─ SSE 事件回放             │
                        └──┬───────────┬──────────────┘
                 tool 消息  │           │ tool 消息
        (endpoint.register/ │           │ (endpoint.register/
         invoke/status/     │           │  invoke/status/
         result/control/    │           │  result/control/
         event)             │           │  event)
   ┌────────────────────────┴─┐   ┌─────┴───────────────────────┐
   │ benchmark(ActionTool)    │   │ policy_runner(SessionTool)   │
   │  run/cancel/status/result│   │  serve/stop/status/result    │
   │  进程内批次执行            │   │  attach-or-launch + 就绪门   │
   └──────┬───────────────▲───┘   └──────┬───────────────▲───────┘
   proprio_state/image/ │ action       policy_command/ │ 推理请求
   policy_command       │              proprio_state/  │ (WS)
          │             │              image           │
          └──── dora 数据面通道(单 MAIN flow)───────────┘
```

- **控制面**:上游 agent 只走 gateway 的 HTTP 接口与 forge_tool 协议;节点侧通过
  ToolEndpointHandler + DoraToolEndpointBinding 把协议消息架在 dora 通道上,与数据面
  共存于同一 MAIN flow。三个节点常驻,无子 flow、无子进程 dora、无手写 adapter。
- **数据面**:benchmark ↔ policy_runner 之间的 proprio_state/image/policy_command/action
  通道语义与旧形态完全一致(7 维 action、8 维 state、双相机 alias、execute_action_steps=5)。
- **通道可靠性**:dora 0.4.1 存在突发丢包缺陷,tool_in/tool_out/policy_command 三个
  易突发通道必须显式 `queue_size: 32`;丢一条 register 续约会触发租约过期误判、丢一条
  tool.event 会破坏 event 序列连续性,因此该参数不可回落默认值。

## 3. 会话工具与推理服务生命周期

policy_runner 的 serve 操作是一个**常驻推理服务会话**:

- **attach-or-launch**:start 先探测 `GET /healthz`;200 则附接(owned=false,不启动、
  不击杀任何进程);否则以 `scripts/start_server.sh --ckpt <bundle 权重目录>
  --policy-config pi05_libero` 启动(owned=true,进程组记录,日志落会话工作区)。
- **三段就绪门**(顺序执行,任一段失败即整体失败):
  1. `/healthz` 200(默认超时 600s);
  2. `infer-once` 成功且 `action_dim=7`;
  3. norm_stats 文件 sha256 等于声明值 `b3a44bb2810436fb62917decaea58bd4d9110255df527dea21e8fd40c960bd84`。
  全部通过才返回 ToolAccepted(details 含 server_url/pid/owned/readiness)。
  失败时 owned 进程被 teardown,start 报 `READINESS_FAIL`(可重试)——环境不修复,
  盲目重试无意义。重复 start 幂等返回当前会话状态,绝不重启。
- **跨批次复用**:就绪会话服务该运行时的所有批次;每次批次前不重启推理服务,
  这是与旧形态(每批手工拉起/清理)的本质差别。
- **stop 是唯一终止路径**:session 在网关侧不设 deadline(见 §4),永远只有 stop 能
  终结它。owned 会话 teardown = SIGTERM 进程组 → 30s 宽限 → SIGKILL(GPU 释放 =
  进程组消亡,可选 nvidia-smi 复核);attached 会话只标记 stopped,不杀进程。
  对已 stopped 会话再 stop 从记录直接回答。
- **未来 VLA 展望**:同一 SessionToolEndpoint 形态可承载「VLA 模型生成 action 支持
  机器人工作」的场景——常驻推理服务、就绪门、stop 释放 GPU 的语义与机器人边
  inference 边执行的需求同构;届时仅需替换服务启动方式与就绪判据,协议与网关层零改动。

## 4. 网关会话支持

- **注册与校验**:ToolSpec/目录白名单从 query|action 放宽到 query|action|session;
  未知语义仍在模型构造层拒绝。
- **HTTP 接口**:`POST /tools/{tool_id}:invoke` 对 action|session 同走保留式提交
  (202 + invocation_id);新增 `POST /invocations/{id}/stop`(镜像 cancel 路由)。
  status/result/events 路由语义无关,原样复用。
- **deadline 豁免**:session invocation 提交时 `deadline_ms=None`,快照不含 deadline;
  超时巡检只标记非 None 项——同一时钟下 action 会被标 unknown 而 session 不受影响。
  单次握手/查询交换仍有界(invoke_timeout 约束)。session 寿命无界是设计决策:
  常驻服务本就没有「批次时长」可估,per-tool 超时覆盖记入未来工作。
- **租约 unknown 语义**:provider 死亡由租约过期 → `mark_instance_ambiguous` 捕获,
  这是 session 中途 provider 失联的唯一探测路径(会话不再被 deadline 扫为 unknown)。
- **stop 簿记**:stop 请求不改变相位——相位始终由 provider 的终态事件与结果驱动;
  网关侧仅镜像 cancel 的三处簿记(stop_status: requested / accepted /
  transport_error / terminal)。stop 到达 provider 后由 `stopped` 终态事件推进相位、
  释放并发栅栏。
- **控制命令语义域**:cancel 只对 Action 生效,stop 只对 Session 生效;跨语义请求
  两端(forge handler 与网关)一律回答 unsupported,不静默、不降级。

## 5. 动作工具:基准测试

benchmark 节点实现 ActionToolEndpoint(descriptor:run / action / cancellable /
status_supported / max_concurrency=1):

- **参数校验**:严格按 gateway schema 校验(suite 枚举、task_ids 0-9 且 ≤10 项、
  init_state_ids 0-49 且 ≤50 项、num_runs≤5、max_steps≤1000、seed、未知 key 拒绝),
  拒绝即回 INVALID_ARGUMENTS;随后以 invoke 参数覆盖 profile 静态默认,
  `resolve_and_validate_plan` fail-fast(含单批次 ≤500 episode 硬上限)。
- **进程内执行**:批次驱动逻辑并入 endpoint,以 asyncio 任务在节点常驻事件循环中
  执行(不再渲染模板、不再启动子 flow);episode 300s / 批次 21600s 的 watchdog 变为
  进程内 asyncio 定时器。重复 execution key 同参数幂等,异参数
  FORGE_EXECUTION_CONFLICT,忙时 BUSY(retryable,details 附活跃 run_id);未知 key 的
  status 直接以 FORGE_EXECUTION_NOT_FOUND 拒绝(provider 不伪造终态相位)。
- **进度事件**:每 episode 完成发 progress 事件,叠加既有 benchmark_status 数据面流。
- **取消 = 部分结果**:cancel 置进程内标志,当前 episode 边界优雅停,已完成 episode
  保留为部分结果,cancelled/partial 终态 + result_file 保留。
- **七字段契约**:ToolResult 恒为七字段(run_id / status(succeeded|failed|cancelled|
  partial)/ completed_episodes / total_episodes / success_rate / result_file /
  failure_summary),schema `benchmark_execution_result_v1` 与旧形态逐字不变——下游
  verify_result 校验脚本无需改动。

## 6. 三语义对比与选型

| 能力 | query | action | session |
| --- | --- | --- | --- |
| 执行模型 | 同步一问一答 | 异步有界执行 | 常驻、无界生命周期 |
| 准入 | 即时阻塞 | 202 + 并发栅栏 | 202 + 并发栅栏(无 deadline) |
| 控制 | 无 | cancel | stop |
| 终态 | 即终 | completed/failed/cancelled/unknown | stopped(provider 死亡 → unknown) |
| 状态/结果查询 | 无 | 有 | 有 |

**benchmark = Action 的四点理由**:

1. 批次天然有界:episode 数与单步上限确定,执行时长可估,契合 Action 的 deadline 模型;
2. 取消语义清晰:中止批次 = 停止当前 episode、保留部分结果,恰是 Action cancel 契约;
3. 终态结果即交付物:七字段结果是调用方唯一关心物,契合「result 只查询一次」模型;
4. 并发上限明确:单批次独占仿真器(max_concurrency=1),Action 的并发栅栏原样表达。

**policy_runner = Session 的理由**:推理服务是跨批次常驻资源,其生命周期(拉起、
就绪、复用、释放)远超单次执行边界;无界 + stop 唯一终止 + 状态可查询的 Session
契约与之一一对应。若硬套 Action,每个批次都要背负一次「启动 + 就绪门 + teardown」,
既无 deadline 可设,又丢失跨批次复用收益。

## 7. 技能打包与锁定

- **锁契约**:`artifact_type: executable_tar_gz` + `entrypoint` + `sha256`(GitHub
  Release digest),tar 根目录仅含 entrypoint 单二进制;安装器逐条校验
  (sha256 必须为 64 位小写 hex)。
- **节点构建下放 node 仓**:PyInstaller spec、构建脚本、entry shim 全部归属节点仓库
  (benchmark / policy_runner 各自 build 目录);Skill 只保留锁与配置。构建脚本内以
  `tar -tzf` 断言单 entrypoint,失败即发布阻断。
- **权重进 bundle**:π0.5-libero 权重(~12.4GB,params/ + assets/ 布局)在打包时位于
  skill 源目录暂存位(gitignored),`package_skill.py` 的 archive-manifest 逐文件
  SHA-256 覆盖之;权重不进入任何代码仓库,运行时由 bundle 解包位置注入
  (session 配置 `weights_dir` 相对 bundle 根,start args 可覆盖)。
- **本地 registry 覆盖**:`PAOS_RESOURCE_REGISTRY_URL` 指向本地服务,提供
  `/v1/forge-nodes/<artifact_id>` → `{download_url, artifact_id, mode: direct}` 与
  `/assets/*.tar.gz` 静态文件,即可用 `paos skill install <bundle> --yes` 完成闭环。
- **不可变性**:已发布资产(Release asset / TOS 对象键 / artifact_id / digest)一律
  不覆盖;gateway 因新增 session 能力重建为新版本 1.1.0(不复用 1.0.2 的
  artifact_id 与 digest)。正式 registry 登记与公开 release 管线属维护者后续工作,
  本地 E2E digest 不回写正式 registry。

## 8. 外部服务与环境边界

- **openpi 生命周期归 session**:serve_policy 进程不再是部署脚本的手工产物,而是
  `kai0_libero.policy` session 的 owned 资源(attach-or-launch + stop teardown)。
- **conda 仿真环境归 benchmark node 仓**:LIBERO 运行所需的 python 环境由节点仓库
  的构建/安装步骤准备,Skill 不携带环境。
- **LIBERO 资产归 node 仓**:仿真资产与官方数据集属节点仓库部署范畴,bundle 不含。
- **推理运行时归 policy_runner node 仓**:server venv(python3.12 + jax)由节点仓库
  setup 脚本安装,start_server.sh 是其唯一入口。
- **GPU ≥16GB 为硬件前置**:π0.5-libero 推理的内存基线;无 GPU 环境表现为
  READINESS_FAIL(快速失败,不挂起)。
- **bundle 体积**:12.4GB 权重使安装变慢(可接受),文档在此注明;TOS 上传由维护者
  手工完成,对象键不覆盖。

## 9. 端到端验证

分层矩阵(联网命令一律去除代理变量):

| 层 | 内容 | 门控 |
| --- | --- | --- |
| L0 | 各仓单元/契约测试:forge session dispatch 套件、gateway 翻转+session 流+deadline 豁免、benchmark endpoint 契约、policy_runner 会话测试 | 无 GPU |
| L1 | gateway HTTP session API:register→invoke→202→accepted→stop→stopped→result;重复 start 幂等;deadline 豁免;租约过期→unknown | 无 GPU |
| L2 | benchmark action:gateway + benchmark 二进制 + 恒值 7 维 action 桩;1-episode 计划 202→accepted→SSE 进度→七字段终态;取消→cancelled/partial + result_file | conda 仿真环境 |
| L3 | session 生命周期:A 附接(预起服务→owned=false)/ B 拉起(owned=true)/ C 复用(真实批次跨批不重启)/ D stop(owned 时 nvidia-smi 无残留)/ E 无 GPU 无服务→快速 READINESS_FAIL | GPU |
| L4 | 打包闭环:三二进制单 entrypoint 断言→权重注入打包→本地 registry 覆盖→`paos skill install --yes`→解包布局/entrypoint 可执行/权重在位→dora 3 节点流启动→结果符合 benchmark_execution_result_v1→queue_size=32 下租约不丢 | 无 GPU;权重注入与真 libero 二进制待环境 |

环境缺失的层降级为 fake/stub 单测并标注 env-gated,不伪造通过。

## 10. 实现状态表

| 项 | 状态 |
| --- | --- |
| forge handler session dispatch(含语义域控制) | 已实现并发布(forge-tool-v0.2.0 tag 已推 gitlab dev) |
| gateway session spec 校验、stop 路由、deadline 豁免、stop 簿记 | 已实现(feat/tool-session → 1.1.0) |
| benchmark ActionToolEndpoint(libero) | 已实现(真实二进制待 conda 环境构建) |
| policy_runner SessionToolEndpoint(kai0_runner) | 已实现(二进制需按 SPECPATH 修复重建,旧 digest 过期) |
| kai0-libero skill 3 节点迁移(双工具 + 新锁契约) | 本轮实现 |
| bundle 交付(含权重,本地 registry 闭环) | registry 闭环已验(libero 暂以占位 shim 走通安装契约);权重注入待用户暂存权重后打包 |
| E2E L0-L1 | 通过(各仓测试全绿;gateway HTTP session 流含 stop/并发释放/deadline 豁免) |
| E2E L2-L3 | 环境门控(conda 仿真环境 / GPU 与权重未就绪),不伪造通过 |
| E2E L4 | 机制闭环通过(三节点下载→sha256 校验→单 entrypoint 解包→可执行);dora 3 节点全流与权重在位待环境 |
| registry 正式登记 nodes.yaml/skills.yaml | 未来(维护者) |
| 公开 release 管线(GitHub Release / TOS 上传) | 未来(维护者,手工) |
| 上游 agent 的 session 桥接工具(PAOS agent 层) | 未来 |
| 多会话并发 / per-tool 超时覆盖 / VLA 场景 | 未来 |

### 10.1 下一步:测试线与发布收尾(2026-08-27)

forge-tool-v0.2.0 已正式发布;forge 分支治理同步完成(master 合并进 dev,以 master 为准,dev 仅保留本轮 tool 相关内容)。剩余工作按依赖排序:

| # | 工作 | 依赖 | 环境门槛 |
| --- | --- | --- | --- |
| 0a | gateway vendored forge_tool 对齐 v0.2.0(dora.py 存在差异);对齐后重建 gateway 1.1.0 二进制、更新 sha256 | — | 无 |
| 0b | kai0_policy 二进制重建(SPECPATH 修复 317533a 之后,旧 digest 过期)并重取 sha256 | — | 无 |
| 1 | libero 真实二进制构建(make_node_bundle.sh + 单 entrypoint 断言 + sha256) | conda LIBERO 环境 | 环境门控 |
| 2 | libero 契约单测(tests/test_contracts.py,conda 环境内) | 1 | 环境门控 |
| 3 | libero/kai0_runner 锁刷新(rev=forge-tool-v0.2.0 已可解析;uv.lock 固化旧 sha 则重锁) | — | 无 |
| 4 | skill.yaml 三节点锁回填(artifact_id / entrypoint / sha256 = 正式 Release digest) | 0a / 0b / 1 | 无 |
| 5 | L2 benchmark action E2E(gateway + libero 二进制 + 恒值 7 维 stub;202→accepted→SSE 进度→七字段终态;cancel→cancelled/partial) | 0a / 1 | conda libero-bench |
| 6 | L4 打包闭环(权重注入→打包→本地 registry 覆盖→install→dora 3 节点流→结果契约→queue_size=32 租约不丢) | 4 + 权重 12.4GB | 权重下载 |
| 7 | L3 session 生命周期(A 附接 / B 拉起 / C 跨批复用 / D stop+GPU 释放 / E 无 GPU 快速失败) | 0b / 6 | GPU |

## 11. 风险与限制

1. **外置 provider 租约语义**:provider 死亡探测依赖租约过期 → unknown(歧义语义),
   调用方需 reconcile 而非盲目重跑;session 中途失联同样只此一条路径。
2. **GPU 前置**:无 GPU 即 READINESS_FAIL,快速失败不挂起;但 GPU 归属争用
   (他方占用 / 多会话并发)本轮未治理。
3. **bundle 体积**:12.4GB 权重使安装/分发变慢;增量分发与资产拆分留待未来。
4. **dora 队列约束**:queue_size=32 是 0.4.1 缺陷的实测止血参数,依赖 dora 版本
   行为;升级 dora 后需回归验证突发通道。
5. **vendored 协议层漂移**:gateway 内嵌 forge_tool 协议层拷贝与 canonical 仓库需
   同步演进,版本不对齐会以 ImportError/行为差异显现,commit 需记录 canonical rev。
6. **正式 digest 回填**:锁内 sha256 以正式 Release digest 为准;本地 E2E digest
   只服务于本地闭环,正式发布前必须回填并复核 artifact_id 未覆盖。
