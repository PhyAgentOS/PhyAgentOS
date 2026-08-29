# Benchmark 类 Skill 架构:paos-gateway-policy-runner-benchmark(kai0-libero 适配)

> 状态:本文档为**已实现架构契约文档**(2026-08-29 E2E 全链验证通过,见 §10)。
> 操作步骤类规范以技能开发与发布文档为准,本文只描述架构与契约。
> 注意:skill 树内的部分 README 仍描述早期 Action 形态,以本文档为准(已知不一致,见 §11)。

## 1. 背景与目标

kai0-libero 是「跑 LIBERO 仿真基准」的典型 benchmark 类 Skill。其旧形态由四个节点与
约 780 行手写 wire adapter 组成:adapter 把 Tool 请求翻译成批次子流程,批次以子进程
dora run 启动,推理服务(openpi serve_policy)则完全游离在技能生命周期之外,由部署脚本
手工拉起、手工清理。

目标形态收敛为 **paos-gateway-policy-runner-benchmark** 三节点单流程:

- **gateway** — 控制面枢纽。HTTP 侧的 Tool invoke/status/result/stop 与
  forge_tool endpoint 协议在此汇合,语义分发(Query/Session)与并发/租约管理
  全部内聚。
- **policy-runner**(kai0_policy)— 推理服务的常驻生命周期所有者,注册为
  **Session tool**(attach-or-launch + 三段就绪门 + stop 释放 GPU)。
- **benchmark**(libero_benchmark)— 仿真基准的执行者,`benchmark.controller`
  上挂 **describe(query)+ run(session)** 两个操作:**一个 session = 一个批次**,
  stop 在 episode 边界落停,已完成集作 partial 结果。

本轮适配性结论:

- benchmark 用 **Session** 语义表达:批次执行时长不可估(episode 数与单步上限是
  上界,真实耗时随策略行为漂移),且 stop 在 episode 边界优雅停、保留部分结果的
  语义与 Session 的 stopping→stopped 相位一一对应;Action 的 deadline/cancel 模型
  反而装不下「边界停 + partial 保留」的契约。
- policy-runner 用 Session 语义表达:常驻推理服务、跨批复用、stop 释放 GPU,
  与 Session 的无 deadline、stop 唯一终止、状态可查询契约一一对应。
- 节点单独落库:benchmark 与 policy-runner 的代码、构建、测试归属各自节点仓库,
  Skill 只保留锁与配置;最终交付物只有 skill bundle(权重不进 bundle,见 §8)。

## 2. 总体架构

```mermaid
flowchart TB
    subgraph AGENT[上游 agent(HTTP)]
        A1[POST /tools/&#123;tool_id&#125;:invoke]
        A2[POST /tools/&#123;endpoint&#125;/&#123;op&#125;:invoke]
        A3[GET /invocations/&#123;id&#125;|/result|/events]
        A4[POST /invocations/&#123;id&#125;/stop]
    end

    subgraph GW[gateway 控制面]
        G1[语义分发 query / session]
        G2[ToolSpec / 目录 / 租约]
        G3[并发栅栏 + deadline 豁免]
        G4[stop 簿记 + SSE 事件回放]
    end

    subgraph BM[libero_benchmark]
        B1[benchmark.controller]
        B2[describe query:进程内能力白名单]
        B3[run session:一批次一 session]
        B4[runner:episode 边界 stop 消费点]
    end

    subgraph PR[kai0_policy]
        P1[policy.runner serve session]
        P2[attach-or-launch + 三段就绪门]
        P3[常驻推理服务]
        P4[stop 释放 GPU]
    end

    A1 --> G1
    A2 --> G1
    A3 --> G2
    A4 --> G4
    G1 <-->|tool 协议 over dora| BM
    G1 <-->|tool 协议 over dora| PR
    B3 <-->|proprio_state / image / action| P3
    B3 -->|policy_command| P3
```

- **控制面**:上游 agent 只走 gateway 的 HTTP 接口与 forge_tool 协议;节点侧通过
  ToolEndpointHandler + DoraToolEndpointBinding 把协议消息架在 dora 通道上,与数据面
  共存于同一 MAIN flow。三节点常驻,无子 flow、无子进程 dora、无手写 adapter。
- **数据面**:benchmark ↔ policy-runner 之间的 proprio_state/image/policy_command/action
  通道语义与旧形态完全一致(7 维 action、8 维 state、双相机 alias、execute_action_steps=5)。
- **通道可靠性**:dora 0.4.1 存在突发丢包缺陷,tool_in/tool_out/policy_command 三个
  易突发通道必须显式 `queue_size: 32`;丢一条 register 续约会触发租约过期误判、丢一条
  tool.event 会破坏 event 序列连续性,因此该参数不可回落默认值。

## 3. 会话工具一:benchmark.controller(describe + run)

`benchmark.controller` 同时挂两个操作:

- **describe(query,mc=1)**:进程内直读能力白名单,永不等待。返回 10 个 task 的
  语言指令、每个 task 50 个 init state、关节名 joint1-7+gripper、默认
  max_steps=300 / num_runs=1 / seed=0。Agent 据此组批。
- **run(session,stoppable=True,status_supported=True,max_concurrency=1,
  cancellable=False)**:一个 session = 一个批次。start 只登记(ToolAccepted 立即
  返回,阻塞的 episode reset 由节点循环在 tool 分发之外执行,不拖慢握手);
  忙/异参冲突/同参幂等按 forge_tool 会话契约处理。

**stop 语义(核心契约)**:

- stop 置位 `stop_requested` 标志,当前 episode **跑完**,在 episode 边界落停,
  已完成集保留为 partial 结果。中途掐掉当前集会被判为数据污染,绝不做。
- 相位推进:accepted →(stop 收下)→ stopping →(边界)→ stopped。
- 已知边界情况:stop 落在**最后一个** episode 期间时,批次以 succeeded 收尾
  (计划跑完先于 stop 检查——episode 已全部完成,无 partial 可言,行为可辩护)。
- 节点被 dora STOP/ERROR 时,在跑 session 立即收成终态(不等边界),partial 输出。

## 4. 会话工具二:policy.runner(serve)

policy-runner 的 serve 操作是一个**常驻推理服务会话**:

- **attach-or-launch**:start 先探测 `GET /healthz`;200 则附接(owned=false,不启动、
  不击杀任何进程);否则以 `scripts/start_server.sh --ckpt <权重目录>
  --policy-config pi05_libero` 启动(owned=true,进程组记录,日志落会话工作区)。
- **三段就绪门**(顺序执行,任一段失败即整体失败):
  1. `/healthz` 200(默认超时 600s);
  2. `infer-once` 成功且 `action_dim=7`;
  3. norm_stats 文件 sha256 等于声明值 `b3a44bb2810436fb62917decaea58bd4d9110255df527dea21e8fd40c960bd84`
     (pi05_libero 官方 norm_stats.json,权重目录 assets/ 下递归 glob 定位)。
  全部通过才返回 ToolAccepted(details 含 server_url/pid/owned/readiness)。
  失败时 owned 进程被 teardown,start 报 `READINESS_FAIL`(可重试)——环境不修复,
  盲目重试无意义。重复 start 幂等返回当前会话状态,绝不重启。
- **跨批次复用**:就绪会话服务该运行时的所有批次;每次批次前不重启推理服务。
- **stop 是唯一终止路径**:session 在网关侧不设 deadline(见 §5),永远只有 stop 能
  终结它。owned 会话 teardown = SIGTERM 进程组 → 30s 宽限 → SIGKILL(GPU 释放 =
  进程组消亡);attached 会话只标记 stopped,不杀进程。对已 stopped 会话再 stop
  从记录直接回答。实测 stop 链路:requested → accepted → stopped,结果
  ToolResult.status=stopped、outputs 含 owned/pid/server_url,GPU 显存回落基线。

## 5. 网关会话支持

- **注册与校验**:ToolSpec/目录白名单从 query|action 放宽到 query|action|session;
  未知语义仍在模型构造层拒绝。
- **HTTP 接口**:`POST /tools/{tool_id}:invoke` 对 session 保留式提交
  (202 + invocation_id);query 走 `POST /tools/{endpoint_id}/{operation}:invoke`;新增
  `POST /invocations/{id}/stop`。status/result/events 路由语义无关,原样复用。
- **deadline 豁免**:session invocation 提交时 `deadline_ms=None`,快照不含 deadline;
  超时巡检只标记非 None 项。单次握手/查询交换仍有界(invoke_timeout 约束)。
  session 寿命无界是设计决策:常驻服务本就没有「批次时长」可估。
- **租约 unknown 语义**:provider 死亡由租约过期 → `mark_instance_ambiguous` 捕获,
  这是 session 中途 provider 失联的唯一探测路径。benchmark 侧租约 TTL 需 120s:
  进程内循环在 episode reset 期间阻塞数十秒不续租,短 TTL 会触发租约过期误判。
- **stop 簿记**:stop 请求不改变相位——相位始终由 provider 的终态事件与结果驱动;
  网关侧簿记 stop_status(requested / accepted / terminal / unsupported)。stop 控制
  载荷固定为 `{"command": "stop"}`(不携带 reason),stop 到达 provider 后由
  `stopped` 终态事件推进相位、释放并发栅栏。

## 6. 七字段结果契约

ToolResult 恒为七字段,与 skill 树 gateway.yaml 的 output_schema 一一对应
(多一个少一个都会让下游 schema 校验失败):

```text
run_id / status / completed_episodes / total_episodes /
success_rate / result_file / failure_summary
```

- **outputs.status 枚举**(给 Agent 看的批次结论):
  `succeeded` | `failed` | `partial`(stop 后已完成集 >0)| `stopped`(一集没跑完)。
- **ToolResult.status**(forge 执行结论)只能是 `succeeded` | `failed` | `stopped`:
  批次被 stop 时两者分叉——outputs.status=partial/stopped 而 ToolResult.status=stopped;
  failed 批次带 ToolError。
- **failure_summary**:stop 批次由 `stopped_summary` 生成,形如
  `stopped after 4/5 episodes`(网关 stop 载荷不带 reason,故无原因后缀)。
- 落盘 schema `benchmark_execution_result_v1` 与旧形态逐字不变——下游
  verify_result 校验脚本无需改动。

## 7. 技能打包与锁定

- **锁契约**:`artifact_type: executable_tar_gz` + `entrypoint` + `sha256`(GitHub
  Release digest),tar 根目录仅含 entrypoint 单二进制;安装器逐条校验。
- **节点构建下放 node 仓**:PyInstaller spec、构建脚本归属节点仓库;构建脚本内以
  `tar -tzf` 断言单 entrypoint,失败即发布阻断。
- **registry 登记**:nodes.yaml 已登记三个 artifact_id(gateway-1.1.0-linux-x86_64、
  libero_benchmark-1.0.0-linux-x86_64、kai0_policy-1.0.2-linux-x86_64,均为公开
  GitHub Release 直链)。
- **不可变性**:已发布资产(Release asset / artifact_id / digest)一律不覆盖;
  gateway 因新增 session 能力重建为新版本 1.1.0(不复用 1.0.2 的 artifact_id)。

## 8. 权重交付:start.sh 预钩

权重(~12.4GB)**不进 bundle**:

- bundle 携带 `start.sh`,由 `paos skill start` 预钩调用:校验/下载权重到
  `~/.PhyAgentOS/cache/weights/<skill>/<version>/`(源为 openpi 官方公开 GCS
  权重,按 sha256 校验),失败即启动中止。
- **交互确认**:y/n 确认后才下载;非 TTY 下 `read -t 30` 默认 N,
  `PAOS_ASSUME_YES=1` 提供免交互出口。
- 权重按 skill+version 缓存,重复 start 跳过下载;三个节点二进制仍走
  registry 直链下载(§7)。

## 9. 外部服务与环境边界

- **openpi 生命周期归 session**:serve_policy 进程不再是部署脚本的手工产物,而是
  `kai0_libero.policy` session 的 owned 资源(attach-or-launch + stop teardown)。
- **conda 仿真环境归 benchmark node 仓**:LIBERO 运行所需的 python 环境由节点仓库
  的构建/安装步骤准备,Skill 不携带环境。
- **LIBERO 资产归 node 仓**:仿真资产与官方数据集属节点仓库部署范畴,bundle 不含。
- **推理运行时归 policy-runner node 仓**:server venv(python3.12 + jax)由节点仓库
  setup 脚本安装,start_server.sh 是其唯一入口。
- **GPU ≥16GB 为硬件前置**:无 GPU 环境表现为 READINESS_FAIL(快速失败,不挂起)。

## 10. 端到端验证(2026-08-29 全链通过)

| 层 | 内容 | 结果 |
| --- | --- | --- |
| L0 | 各仓单元/契约测试(forge session dispatch、gateway session 流、benchmark endpoint 契约、policy 会话) | 全绿 |
| L1 | gateway HTTP session API(register→invoke→202→accepted→stop→stopped→result;deadline 豁免) | 通过 |
| L2 | policy 会话就绪门:healthz→infer-once(action_dim=7)→norm_stats 递归 glob 锚点 | 通过(kai0_policy 1.0.2 二进制) |
| L3 | describe 查询:能力白名单(10 task / 50 init state / joints / defaults) | 通过 |
| L4 | run 批次:1/2/3 episode 批次 succeeded,七字段终态,~60ms/步 | 通过 |
| L5 | stop 全链路:requested→accepted→stopping→stopped;partial 4/5 与 2/3;终态 stop 正确回 terminal;failure_summary 生成 | 通过 |
| L6 | policy session stop:owned teardown,GPU 显存回落,进程组消亡 | 通过 |
| L7 | `paos skill stop kai0-libero`:三节点优雅退出,gateway 下线 | 通过 |
| L8 | 发布闭环:gateway 1.1.0 / libero_benchmark 1.0.0 / kai0_policy 1.0.2 三资产公开;nodes.yaml 三条目登记推送 | 完成 |

skill bundle(kai0-libero 1.0.0)已打包并登记:skills.yaml 采用相对
object_key(`skill-bundles/kai0-libero/1.0.0/kai0-libero-1.0.0.tar.gz`,
sha256 7706ffa8…,19512 bytes),bucket 由部署配置 TOS_BUCKET 决定
(现为私有桶 phyagentos-resource-inner)。

## 11. 实现状态表

| 项 | 状态 |
| --- | --- |
| forge handler session dispatch(含语义域控制) | 已实现并发布 |
| gateway session spec 校验、stop 路由、deadline 豁免、stop 簿记 | 已实现(v1.1.0,已发布) |
| libero_benchmark benchmark.controller(describe query + run session + 边界 stop) | 已实现并发布(v1.0.0) |
| kai0_policy policy.runner serve session(attach-or-launch + 就绪门 + stop 释放 GPU) | 已实现并发布(v1.0.2) |
| kai0-libero skill 三节点迁移(双 Session 工具 + 新锁契约) | 完成(bundle 1.0.0 已打包) |
| start.sh 权重预钩(paos skill start) | 完成(PhyAgentOS feature/forge) |
| nodes.yaml 三条目 registry 登记 | 已提交并推送(dev) |
| skills.yaml 正式登记 | 已提交并推送(dev d31e0df;私有桶 phyagentos-resource-inner + 相对 object_key) |
| skill 树 README 与本文档的一致性 | 已知不一致:README 仍描述早期 Action 形态,暂不改动(按约束) |

## 12. 风险与限制

1. **外置 provider 租约语义**:provider 死亡探测依赖租约过期 → unknown(歧义语义),
   调用方需 reconcile 而非盲目重跑;session 中途失联同样只此一条路径。
2. **GPU 前置**:无 GPU 即 READINESS_FAIL,快速失败不挂起;GPU 归属争用
   (他方占用 / 多会话并发)本轮未治理。
3. **权重体积**:12.4GB 权重按 skill+version 缓存,首次 start 下载耗时可观;
   增量分发留待未来。
4. **dora 队列约束**:queue_size=32 是 0.4.1 缺陷的实测止血参数,依赖 dora 版本
   行为;升级 dora 后需回归验证突发通道。
5. **vendored 协议层漂移**:gateway 内嵌 forge_tool 协议层拷贝与 canonical 仓库需
   同步演进,版本不对齐会以 ImportError/行为差异显现,commit 需记录 canonical rev。
6. **stop 落点依赖控制消息到达时刻**:stop 在当前 episode 期间到达则当前集跑完后停;
   到达时刻的早晚只影响 partial 的集数,不违反「边界停」契约。
