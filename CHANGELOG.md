# Changelog

All notable changes to PhyAgentOS are documented here. Categories follow Keep a Changelog.

## [v4.12.2] - 2026-09-05

回写 v4.12.1 独立 RoboTwin simulation-probe 实现提交 `f88778a`。实现、真实负证据、五维验收结论与
后续执行门禁均未改变；`.codegraph/`、`.cursor/` 仍为未跟踪的用户目录，未纳入提交。

Recorded the v4.12.1 independent RoboTwin simulation-probe implementation commit `f88778a`. The
implementation, real negative evidence, five-dimension acceptance conclusions, and next execution gate are
unchanged; the user-owned `.codegraph/` and `.cursor/` directories remain untracked and uncommitted.

### 文件变更详情 / Detailed changes

- `changelog/2026-09_part2.md:L310-L403`：新增 v4.12.2 双语维护记录，并将 v4.12.1 的
  `Commit: pending` 更新为 `f88778a`。
- `changelog/2026-09_part2.md:L310-L403`: adds the bilingual v4.12.2 maintenance record and replaces the
  v4.12.1 `Commit: pending` marker with `f88778a`.
- `CHANGELOG.md:L5-L95`：同步根日志最近记录及 v4.12.1 implementation commit；未修改运行代码。
- `CHANGELOG.md:L5-L95`: synchronizes the root recent entry and v4.12.1 implementation commit without
  changing runtime code.

### 关键 Diff / Key Diff

```text
Before: v4.12.1 implementation and validation were recorded with Commit: pending.
After:  implementation commit f88778a and pushed branch are explicitly recorded; code and evidence are unchanged.
```

### 验证 / Validation

- `f88778a` 同时为本地 `HEAD` 和 `origin/feature/long-horizon-workflow`；日志 UTF-8 显示正常。
- `git diff --check` 通过；仅两份日志进入定向提交，未跟踪用户目录未暂存。

### Git 提交 / Git Commit

- Implementation commit: `f88778a`
- Branch: `feature/long-horizon-workflow`

## [v4.12.1] - 2026-09-05

收紧独立 RoboTwin simulation probe 的真实性门禁：为 block actor 分配唯一身份，首步前保存 before
snapshot，校验实际 backend revision，并要求目标实体在 lift 阶段真实升高至少 1 cm。修复 client 将
“世界曾变化”错误等同于“仍需 reconciliation”的协议问题，以及启动时双 reset 导致的 revision 漂移。

最终复审进一步实体化并执行 joint/stop policy，将 calibration 与 policy 内容摘要绑定进 approval，校验
runtime limit 的有限有序性和规划/观测速度，并将 worker 固定为 single-use；planning/finalization 失败
统一保存不可变诊断并进入 reset 恢复。scene reset 现在也被如实计为仿真世界变化。

Tightened the independent RoboTwin simulation probe's truthfulness gates: assign unique block identities,
persist the before snapshot before the first step, verify the actual backend revision, and require the target
entity to rise by at least 1 cm during lift. Fixed the client protocol conflating prior world change with pending
reconciliation and removed the startup double-reset revision drift.

The final review also materializes and enforces joint/stop policies, binds calibration and policy digests into the
approval, validates finite ordered runtime limits and planned/observed speeds, makes the worker single-use, and
routes planning/finalization failures through immutable diagnostics and reset recovery. Scene reset is now
truthfully counted as a simulation-world change.

### 文件变更详情 / Detailed changes

- `robotwin_simulation_probe_worker.py:L110-L173,L295-L397,L514-L1225`：绑定审批输入摘要，执行实体化
  policy、runtime/速度/真实 lift 门禁，并统一 finalization/failure/reset；worker 固定 single-use。
- `robotwin_simulation_probe_worker.py:L110-L173,L295-L397,L514-L1225`: binds approved input digests,
  enforces materialized policies plus runtime/speed/real-lift gates, unifies finalization/failure/reset, and makes
  the worker single-use.
- `simulation_probe.py:L41-L108` 与 `test_simulation_probe.py:L1-L656`：收紧 client failure/reconciliation
  contract，并覆盖摘要篡改、limits、失败恢复与 revision 生命周期。
- `simulation_probe.py:L41-L108` and `test_simulation_probe.py:L1-L656`: tighten the client
  failure/reconciliation contract and cover digest tampering, limits, recovery, and revision lifecycle.
- `PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L737-L763`、`STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md:L773-L804`
  与 adapter README `L395-L428`：记录最终真实负证据、五维验收和下一门禁。
- The diagnosis `L737-L763`, implementation review `L773-L804`, and adapter README `L395-L428` record the
  final real negative evidence, five-dimension acceptance, and next gate.

### 关键 Diff / Key Diff

```text
Before: approval bound policy references but not their bytes; final evidence failures could escape recovery;
        scene reset could be reported as no world change.
After:  approval binds calibration/joint/stop SHA-256; all post-reset failures persist diagnostics and reset;
        scene reset is a world change, while negative evidence never becomes readiness.
```

### Validation

- Latest real run: `paos-simulation-probe-20260905T020000p0800-policy-v6` returned `unavailable` before a robot
  step because the left arm failed planning and the right arm exceeded the approved `1.0 rad/s` limit; the scene
  reset was recorded as world change, recovery reset completed, and readiness/motion wiring was not approved.
- Focused simulation-probe conformance: `21 passed`; adapter subset: `158 passed, 2 skipped`; repository:
  `164 passed`; ruff, compileall, and diff-check passed.
- Gateway, Dora, Action executor, and hardware remain disconnected. Commit: `f88778a` on
  `feature/long-horizon-workflow`.

## [v4.12.0] - 2026-09-05

新增独立 RoboTwin simulation-probe producer 与严格 profile-owned client。worker 在专用 approval 和
Franka/task/request 绑定下执行八阶段单候选仿真路线，记录附着几何、planner/joint limits、active
contacts、stop/failure snapshot 和 reset/reconciliation；不接入 Gateway、Dora 或硬件。真实 seed-0
运行在 retreat 检测 `panda_rightfinger/table` active collision，返回 unavailable，未批准 readiness
或 motion wiring。

Added an independent RoboTwin simulation-probe producer and strict profile-owned client. Under dedicated
approval and Franka/task/request bindings, the worker executes an eight-phase single-candidate simulation
route and records attached geometry, planner/joint limits, active contacts, stop/failure snapshots, and
reset/reconciliation; Gateway, Dora, and hardware remain disconnected. The real seed-0 run detected an
active `panda_rightfinger/table` collision during retreat and returned unavailable; readiness and motion
wiring were not approved.

### Detailed changes

- Added the simulation probe worker, profile-owned client/profile, and conformance tests.
- Extended route-evidence snapshot/semantic validation and exported the probe API.
- Updated diagnosis, implementation review, and adapter README with the five-dimension review and negative
  readiness evidence boundary.

### Validation

- Probe/evidence conformance: `19 passed`; adapter composition excluding the PAOS missing-numpy grasp
  proposal module: `145 passed, 2 skipped`.
- Ruff, compileall, and `git diff --check` passed. Real artifact root:
  `/home/yanxu/robotwin20-runtime/artifacts/paos-simulation-probe-20260905T0230Z`.
- Commit: pending on `feature/long-horizon-workflow`.

## Archive

- [2026-09 part 2](changelog/2026-09_part2.md)
- [2026-09](changelog/2026-09.md)

## [v4.11.0] - 2026-09-04

新增独立 route-evidence verifier：消费外部授权 simulation probe 产物，校验附着 geometry、planner route、六项 readiness scope、before/after snapshot、semantic verdict、producer identity 和 SHA-256；verifier 与 worker 始终保持 no-motion，不启动 RoboTwin、Dora、Gateway 或硬件。

Added an independent route-evidence verifier that consumes artifacts from an authorized external simulation probe and validates attached geometry, planner route, six readiness scopes, before/after snapshots, semantic verdict, producer identity, and SHA-256. The verifier and worker remain no-motion and never start RoboTwin, Dora, Gateway, or hardware.

### Detailed changes

- Added `examples/forge-adapters/robotwin20/src/robotwin20_adapter/route_evidence.py`, `runtime/robotwin_route_evidence_worker.py`, `profiles/robotwin20/route-evidence.yaml`, and `tests/test_route_evidence.py`.
- Added strict producer/probe execution binding so external world change is explicit and cannot be confused with verifier no-motion.
- Updated PAOS diagnosis, implementation review, and adapter README with the five-dimension acceptance and remaining motion gate.

### Validation

- Verifier focus: `10 passed`; combined route/readiness/action focus: `80 passed`; repository: `164 passed`.
- Ruff, compileall, and `git diff --check` passed. No RoboTwin `play_once`, Dora, Gateway motion, or hardware was started.
- Commit: `3d72b98` on `feature/long-horizon-workflow`.

## [v4.10.0] - 2026-09-05

新增 simulation route-readiness contract、profile-owned bounded JSONL worker 和外部配置。请求绑定附着物体 geometry/digest、八阶段路线、waypoint frame/速度限幅、workspace 与 stop policy；当前 worker 对真实 planner、附着碰撞、接触动力学、stop controller 和语义验收明确返回 unavailable，保持 no-motion。

Added the simulation route-readiness contract, profile-owned bounded JSONL worker, and external configuration. Requests bind attached-object geometry/digests, eight route phases, waypoint frames/speed limits, workspace, and stop policy; the current worker explicitly returns unavailable for the real planner, attached collision, contact dynamics, stop controller, and semantic verification while remaining no-motion.

### Detailed changes

- Added `examples/forge-adapters/robotwin20/src/robotwin20_adapter/route_readiness.py:L1-L344`, `runtime/robotwin_route_readiness_worker.py:L1-L99`, `profiles/robotwin20/route-readiness.yaml:L1-L18`, and `tests/test_route_readiness.py:L1-L166`.
- Exported route readiness APIs from `robotwin20_adapter/__init__.py:L67-L78,L185-L193`.
- Updated architecture diagnosis, implementation review, adapter README, and monthly changelog.

### Validation

- Route readiness: `9 passed`; combined readiness/action/Gateway focus: `81 passed`; repository: `164 passed`.
- Ruff, compileall, and `git diff --check` passed. No RoboTwin `play_once`, Dora, Gateway motion executor, or hardware was started.
- Git commit: `ada59b5` on `feature/long-horizon-workflow`.

## [v4.9.0] - 2026-09-05

新增独立的 simulation-motion authorization profile/schema。`simulation_authorization.py` 严格绑定 runtime/evidence manifest digest、任务/场景/Franka 本体身份、四类 readiness scope、审批记录、停止策略和 before/after semantic snapshot；默认配置为 disabled/no-motion，不启动任何 worker 或动作。

Added an isolated simulation-motion authorization profile/schema. `simulation_authorization.py` binds runtime/evidence-manifest digests, task/scene/Franka identity, four readiness scopes, approval records, stop policy, and before/after semantic snapshots; the checked-in profile is disabled/no-motion and starts no worker or action.

### Detailed changes

- Added `examples/forge-adapters/robotwin20/src/robotwin20_adapter/simulation_authorization.py:L1-L443`, `profiles/robotwin20/simulation-motion.yaml:L1-L47`, and `tests/test_simulation_authorization.py:L1-L238`.
- Exported the schema/profile loader from `robotwin20_adapter/__init__.py:L55-L64,L143-L149`.
- Updated architecture diagnosis, five-dimension review, adapter README, and `changelog/2026-09_part2.md`.

### Validation

- Simulation profile conformance: `10 passed`; readiness/action/Gateway focused suite: `81 passed`; repository: `164 passed`.
- Ruff, compileall, and `git diff --check` passed. No RoboTwin `play_once`, Dora, Gateway motion executor, or hardware was started.
- Git commit: `0447dab` on `feature/long-horizon-workflow`.

## [v4.8.0] - 2026-09-05

将 Action 生命周期改为 invocation-first：先创建 invocation/attempt，再启动 deferred provider；保留失败、取消、超时和 unknown 语义。

Changed the Action lifecycle to invocation-first: allocate invocation/attempt before starting deferred providers while preserving failure, cancel, timeout, and unknown semantics.

### Detailed changes

- Updated `PhyAgentOS/forge/capability_runtime/ports.py:L17-L23`, `runtime.py:L204-L270`, and pick-place endpoints/gateway at `object_acquire.py:L51-L60,L410-L488`, `object_place.py:L56-L65,L487-L565`, `fake_gateway.py:L272-L307,L494-L795`.
- Added provider identity/start-failure/deferred cancel-stop conformance and documented the five-dimension review.

### Validation

- Focused Action/Gateway tests: `58 passed`; repository: `164 passed`; pick-place suite: `256 passed`.
- No simulation motion, Dora, or hardware execution was enabled.

## [v4.7.14] - 2026-09-05

记录仿真 motion executor 的前置阻断，修订顺序为 invocation-first、独立 simulation authorization、完整 readiness、before/after snapshot 与语义验收后再运动。

Recorded simulation motion-executor blockers and revised the order to invocation-first, isolated simulation authorization, complete readiness, before/after snapshots, and semantic verification before motion.

### Detailed changes

- Updated `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L585-L630` and `docs/forge/STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md:L606-L628`.
- Verified no-motion Action/Gateway `52 passed` and repository `161 passed`; no RoboTwin motion stepping.

## [v4.7.10] - 2026-09-05

回写 v4.7.9 Action readiness gate 实现提交哈希 `83c74ff`；未修改运行逻辑，用户目录 `.codegraph/` 与 `.cursor/` 未纳入提交。

Recorded the v4.7.9 Action readiness-gate implementation commit hash `83c74ff`; runtime logic was unchanged, and user directories `.codegraph/` and `.cursor/` were excluded from the commit.

### Detailed changes

- Updated `changelog/2026-09_part2.md` with the completed maintenance record and exact implementation commit.
- Kept user-owned `.codegraph/` and `.cursor/` directories out of the change.

### Validation

- Verified the working tree contains only the intended changelog/index edits plus pre-existing untracked user directories.
- Git commit: `e6883f8` on `feature/long-horizon-workflow`.

## [v4.7.9] - 2026-09-05

接入已人工审核 readiness evidence 的 Action admission no-motion gate。`object.acquire`/
`object.place` 在创建 Gateway invocation 前校验 manifest/review/evidence SHA-256、同一
scene/candidate-set/frame/calibration、candidate/entity、worker/embodiment identity、三项
readiness checks 和 `motion_authorized=false`；Fake Gateway action context 显式返回 no-motion，
并拒绝 provider 报告的 `world_change_started=true`。manifest/review/artifact 路径由
`profiles/robotwin20/action-readiness.yaml` 和环境变量注入。

Added a no-motion Action-admission gate backed by manually reviewed readiness evidence. Before
allocating a Gateway invocation, `object.acquire`/`object.place` validate manifest/review/evidence
SHA-256, scene/candidate-set/frame/calibration, candidate/entity, worker/embodiment identity, all
readiness checks, and `motion_authorized=false`. Fake Gateway Action contexts explicitly expose
no-motion and reject providers reporting `world_change_started=true`. Manifest/review/artifact
paths are injected through `profiles/robotwin20/action-readiness.yaml` and environment variables.

### Detailed changes

- Added `examples/forge-adapters/robotwin20/src/robotwin20_adapter/action_readiness.py:L1-L274` and `profiles/robotwin20/action-readiness.yaml:L1-L4`.
- Added `examples/forge-adapters/robotwin20/tests/test_action_readiness_gate.py:L1-L273`.
- Updated Skill Action endpoints and Fake Gateway at `examples/forge-skills/pick-place-workflow/src/pick_place_workflow/object_acquire.py:L51-L60,L410-L488`, `object_place.py:L56-L65,L487-L565`, and `fake_gateway.py:L261-L297,L375-L410`.
- Updated architecture diagnosis, five-dimension review, and adapter README.

### Validation

- Focused Action/Gateway/readiness conformance: `52 passed`.
- Ruff and `git diff --check` passed; real Franka manifest gate loaded all `50` evidence candidates.
- No RoboTwin `play_once`, Dora, Action stepping, or hardware motion was invoked.

## [v4.7.6] - 2026-09-04

完成 Franka `blocks_ranking_rgb` 的独立 readiness worker 证据闭环，并将 live worker 接入 adapter 的 bounded JSONL profile seam。相同 `blocks_ranking_rgb-0-1/head_camera` 上生成 12 个 geometry/point-cloud derived artifacts，GraspGen funnel 为 `72→72→71→71`，Curobo no-motion worker 为 `50/71` prepared；50 个 evidence ref 唯一且全部绑定 request、candidate-set、observation、scene、frame、calibration、worker 和 profile digest。

Completed the independent readiness-worker evidence loop for Franka `blocks_ranking_rgb` and wired the live worker through the adapter's bounded JSONL profile seam. On the same `blocks_ranking_rgb-0-1/head_camera`, 12 geometry/point-cloud derived artifacts were verified, GraspGen produced funnel `72→72→71→71`, and the Curobo no-motion worker prepared `50/71`; all 50 evidence refs are unique and bound to request, candidate-set, observation, scene, frame, calibration, worker, and profile digest.

### Detailed changes

- Added `runtime/robotwin_readiness_worker.py` live schema, strict freshness/provenance/pose checks, and per-evidence no-motion bindings.
- Added `profiles/robotwin20/readiness-live.yaml`, `ReadinessLiveClient`, and `build_live_readiness_evaluator`; added schema/motion-drift tests.
- Updated architecture diagnosis, implementation review, and adapter README. Manual review authorizes only the next no-motion Action/Gateway review; no Action, Dora, attached-object transport, or hardware motion is authorized.

### Validation

- Adapter readiness/backend tests: `50 passed`; repository with explicit async plugin: `161 passed`.
- External live profile → worker → PAOS `manipulation.prepare`: `available`, `50 prepared`, all checks `pass`, `motion_authorized=false`.
- Ruff, compileall, and `git diff --check` passed. Evidence manifest: `b0cd2298b84bbc4be0470fb66da4b543928836dd026433ae7e0861cb691fec79`.

## [v4.7.4] - 2026-09-04

完成 Franka `blocks_ranking_rgb` readiness 输入审计：capture 缺少同一 scene revision 的 geometry/candidate，现有 GraspGen 结果不可跨场景复用，因此安全记录 `unavailable`，未启动 IK/碰撞或动作链路。

Completed the Franka `blocks_ranking_rgb` readiness-input audit: the capture lacks same-revision geometry/candidates and the existing GraspGen result cannot be reused across scenes, so the gate safely records `unavailable` without starting IK/collision or motion paths.

详细记录见 [FRANKA_READINESS_INPUT_AUDIT_20260904](docs/forge/FRANKA_READINESS_INPUT_AUDIT_20260904.md)。

## [v4.7.5] - 2026-09-04

回写 v4.7.4 Franka readiness 输入审计提交哈希 `ee2144e`；实现和执行顺序不变。

Recorded the v4.7.4 Franka readiness-input audit commit hash `ee2144e`; implementation and execution order are unchanged.

## [v4.7.1] - 2026-09-04

回写 v4.7.0 本体 profile 与 readiness identity 实现提交哈希 `30bf3ed`；没有修改实现行为。

Recorded the v4.7.0 embodiment-profile and readiness-identity implementation commit hash `30bf3ed`; implementation behavior is unchanged.

## [v4.7.2] - 2026-09-04

readiness profile 现在校验绑定的 runtime profile 文件及 SHA-256，防止 benchmark/本体配置漂移后复用旧 evidence。

The readiness profile now verifies its bound runtime-profile file and SHA-256, preventing stale evidence reuse after benchmark or embodiment drift.

## [v4.7.0] - 2026-09-04

完成 RoboTwin adapter 的可替换 embodiment profile 与 readiness 身份绑定。
Franka `blocks_ranking_rgb`（`[franka-panda, franka-panda, 0.8]`）已通过实际
no-motion preflight/scene capture；未接入 Action、Gateway、Dora 或硬件运动。

Completed replaceable RoboTwin embodiment profiles and readiness identity
bindings. Franka `blocks_ranking_rgb` (`[franka-panda, franka-panda, 0.8]`)
passed real no-motion preflight/scene capture; Action, Gateway, Dora, and
hardware motion remain disconnected.

### Detailed changes

- Backend/preflight now validate native dual-arm versus two-single-arm topology and load `franka-blocks-ranking.yaml`.
- Readiness fixture, evidence manifest, worker response, and immutable replay artifact now require matching robot/gripper/topology/planner/profile-digest bindings.
- Updated architecture diagnosis, execution order, and adapter replacement guidance.

### Validation

- Adapter conformance: `71 passed, 1 skipped`; focused backend/preflight/readiness: `37 passed`; repository: `161 passed` with `pytest_asyncio`.
- RoboTwin20 Franka pair preflight: `ready=true`; no-motion capture produced RGB/depth/state/calibration.
- Ruff, compileall, and `git diff --check` passed.

## [v4.5.4] - 2026-09-05

回写 v4.5.3 GraspGen 验收日志维护提交哈希 `36d940d`，并完成 v4.5.4 索引提交 `0cfcd56`；没有修改实现、测试或执行顺序。

Recorded the v4.5.3 GraspGen acceptance-log maintenance commit hash `36d940d` and completed the v4.5.4 index commit `0cfcd56`; implementation, tests, and execution order are unchanged.

## [v4.5.1] - 2026-09-05

回写 v4.5.0 provider no-motion 真实链路验收提交哈希 `9a2af2e`；没有修改实现、测试或执行顺序。

Recorded the v4.5.0 provider no-motion live-chain acceptance commit hash `9a2af2e`; implementation, tests, and execution order are unchanged.

## [v4.5.2] - 2026-09-05

修复 GraspGen worker 的 JSONL stdout conformance，并通过真实 `entity://red-rectangular-block-1` 点云完成 no-motion `grasp.propose`，返回 24 个 provider-neutral candidates；未进入 readiness、Action 或运动。

Fixed GraspGen worker JSONL stdout conformance and completed a no-motion `grasp.propose` on the real `entity://red-rectangular-block-1` point cloud, returning 24 provider-neutral candidates; readiness, Action, and motion remain gated.

### Validation

- Adapter: `104 passed`; repository: `161 passed`; pick-place: `256 passed`; Ruff and compileall passed.
- Evidence manifest: `a7627a6d8583bf4da502dfe1deaf8c3ec1e978f8f274ede545446614f43ae336`.

## [v4.5.3] - 2026-09-05

回写 v4.5.2 GraspGen live provider seam 实现提交哈希 `aff62a5`；没有修改实现、测试或执行顺序。

Recorded the v4.5.2 GraspGen live provider seam implementation commit hash `aff62a5`; implementation, tests, and execution order are unchanged.

## [v4.5.0] - 2026-09-05

完成已接入 provider 的真实 RoboTwin no-motion 链路验收，并修复 runtime stdout 可审计性；按架构集成、失败路径、权威边界、配置、可维护性五维复审无 Blocker/Major。当前仍未进入 Action/Gateway、Dora 或机器人运动。

Completed the live RoboTwin no-motion chain review for currently integrated providers and fixed runtime stdout auditability; the five-dimension review found no Blocker/Major. Action/Gateway, Dora, and robot motion remain deferred.

### Detailed changes

- `examples/forge-adapters/robotwin20/runtime/robotwin_backend.py:L18,L384-L412`: redirect simulator/runtime stdout noise to stderr and emit one machine-readable JSON document on stdout.
- `examples/forge-adapters/robotwin20/tests/test_robotwin_backend_contract.py:L79-L118`: add stdout/stderr contract coverage.
- `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L462-L483`, `docs/forge/STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md:L509-L522`, `examples/forge-adapters/robotwin20/README.md:L227-L236`: record the run, intermediate perception artifacts, unavailable providers, motion flags, and final manifest digest.

### Validation

- Isolated adapter tests with explicit async plugin and dependency paths: `103 passed`; repository: `161 passed`; pick-place with required path and async plugin: `256 passed`.
- Ruff, compileall, and `git diff --check` passed.
- Run manifest: `/home/yanxu/robotwin20-runtime/artifacts/paos-real-chain-20260905T0020Z/run_manifest.json`, SHA-256 `da7a81bd2efccbf70312428a3adeef10babe2d465734f63f7c90444297389b46`; all motion flags are `false`.
- GraspGen (`GRASPGEN_PYTHON`) and readiness (`READINESS_FIXTURE`) are unavailable; no `object.acquire`/`object.place` was attempted.

## [v4.4.0] - 2026-09-04

固化独立 readiness worker 的 no-motion projection 为 adapter-local、不可变 canonical replay artifact；保持人工审核门禁，不进入真实 Action/Gateway wiring。

Persisted independently validated readiness worker no-motion projections as immutable adapter-local canonical replay artifacts; retained the manual-review gate and did not enter real Action/Gateway wiring.

### Validation

- Readiness/replay/process: `25 passed`; repository: `161 passed`; dependency-free adapter subset: `16 passed`; pick-place: `256 passed`.
- Ruff, compileall, and `git diff --check` passed. Artifact is not a PAOS EvidenceBundle or motion authorization.

## [v4.4.1] - 2026-09-04

回写 v4.4.0 readiness replay artifact 实现提交哈希 `a2f972a`；没有修改实现、测试或执行顺序。

Recorded the v4.4.0 readiness replay artifact implementation commit hash `a2f972a`; implementation, tests, and execution order were unchanged.

## [v4.3.4] - 2026-09-04

回写 v4.3.3 readiness calibration identity 修复提交哈希 `20c6ad6`；没有修改实现、测试或执行顺序。

Recorded the v4.3.3 readiness calibration-identity fix commit hash `20c6ad6`; implementation, tests, and execution order were unchanged.

## [v4.3.3] - 2026-09-04

修复 readiness replay 中 calibration identity 未完整绑定的问题；fixture、request、manifest 现在三方一致校验。

Fixed incomplete calibration identity binding in readiness replay; fixture, request, and manifest now require three-way consistency.

### Validation

- Readiness/replay/process: `34 passed`; dependency-free adapter subset: `44 passed`.
- Ruff, compileall, and `git diff --check` passed.

## [v4.3.2] - 2026-09-04

回写 v4.3.1 日志维护提交哈希 `8833784`；没有修改实现、测试或执行顺序。

Recorded the v4.3.1 changelog-maintenance commit hash `8833784`; implementation, tests, and execution order were unchanged.

## [v4.3.1] - 2026-09-04

回写 v4.3.0 readiness evidence manifest 实现提交哈希 `23364de`；没有修改实现、测试或执行顺序。

Recorded the v4.3.0 readiness evidence-manifest implementation commit hash `23364de`; implementation, tests, and execution order were unchanged.

## [v4.3.0] - 2026-09-04

完成 readiness replay evidence manifest 的 no-motion 绑定校验，并按架构集成、失败路径、权威边界、配置、可维护性五个维度复审通过。

Implemented no-motion binding validation for the readiness replay evidence manifest and passed review across architecture integration, failure paths, authority boundaries, configuration, and maintainability.

### Detailed changes

- `examples/forge-adapters/robotwin20/runtime/readiness_replay_worker.py`: strict hash-pinned evidence manifest validation for candidate-set, calibration, source, and timezone-aware capture timestamps.
- `examples/forge-adapters/robotwin20/src/robotwin20_adapter/readiness_profile.py`: external manifest path, permission, digest, and duplicate-argument gates.
- `examples/forge-adapters/robotwin20/tests/test_readiness_replay.py`, `profiles/robotwin20/readiness-replay.yaml`: manifest conformance and profile configuration.

### Validation

- Readiness/replay/process tests: `34 passed`; dependency-free adapter subset: `44 passed`; repository: `161 passed`; pick-place: `256 passed`.
- Ruff, compileall, and `git diff --check` passed.
- No real IK, collision engine, Action, Gateway, Dora, hardware, or motion path was started.

## [v4.2.1] - 2026-09-04

回写 v4.2.0 readiness replay 实现提交哈希 `103db24`；没有修改实现、测试或执行顺序。

Recorded the v4.2.0 readiness replay implementation commit hash `103db24`; implementation, tests, and execution order were unchanged.

## [v4.2.0] - 2026-09-04

完成 readiness evidence replay worker/profile 的 no-motion conformance，并按五个维度复审通过；保持 PAOS projection 和动作权限边界不变。

Implemented no-motion conformance for the readiness evidence replay worker/profile and passed the five-dimension review; PAOS projection and motion-authority boundaries remain unchanged.

### Detailed changes

- `examples/forge-adapters/robotwin20/runtime/readiness_replay_worker.py`: hash-pinned fixture replay with complete case identity matching and no-motion output.
- `examples/forge-adapters/robotwin20/src/robotwin20_adapter/readiness_profile.py`: fixture digest/path/permission gates and worker identity validation through the existing JSONL process boundary.
- Existing `PhyAgentOS/forge/capability_runtime/manipulation_prepare.py` mapping normalization remains the final PAOS owner.
- `examples/forge-adapters/robotwin20/tests/test_readiness_replay.py`, `profiles/robotwin20/readiness-replay.yaml`: replay and profile conformance coverage.
- `examples/forge-adapters/robotwin20/src/robotwin20_adapter/readiness.py`: expose explicit readiness adapter teardown for process-backed evaluators.

### Validation

- Replay/readiness/process tests: `28 passed`; dependency-free adapter subset: `38 passed`; repository: `161 passed`; pick-place: `256 passed`.
- Ruff, compileall, and `git diff --check` passed.
- Replay is protocol evidence only; no real IK, collision engine, Action, Gateway, Dora, hardware, or motion path was started.
- Full RoboTwin20 adapter collection remains environment-limited by optional `numpy` and missing pick-place source-path injection; this does not invalidate the dependency-free conformance subset.

## [v4.1.0] - 2026-09-04

完成 RoboTwin20 独立 `ReadinessEvaluator` conformance，并按五个维度复审通过；保持 provider-neutral、dry-run/no-motion。Hephaestus 仅作 clean-room 语义参考，未接入运行时代码。

Implemented the independent RoboTwin20 `ReadinessEvaluator` conformance and passed the five-dimension review; kept provider-neutral, dry-run/no-motion behavior. Hephaestus was used only as a clean-room semantic reference, with no runtime code integrated.

### Detailed changes

- `examples/forge-adapters/robotwin20/src/robotwin20_adapter/readiness.py`: strict request/result binding, evidence validation, evaluator isolation, and fail-closed adapter boundary.
- `PhyAgentOS/forge/capability_runtime/manipulation_prepare.py`: strict normalization of adapter mappings while preserving PAOS ownership of projection and `motion_authorized=false`.
- `examples/forge-adapters/robotwin20/tests/test_readiness.py`: readiness and PAOS integration conformance coverage.
- `examples/forge-adapters/robotwin20/README.md`, `docs/forge/STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md`, `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md`: updated implementation order and reference boundary.

### Validation

- Readiness tests: `14 passed`; dependency-free adapter subset: `30 passed`; repository: `161 passed`; pick-place: `256 passed`.
- Ruff, compileall, and `git diff --check` passed.
- No real IK/collision engine, Action, Gateway, Dora, hardware, or motion path was started.

## [v4.1.1] - 2026-09-04

回写 v4.1.0 实现提交哈希；没有修改实现、测试或执行顺序。

Recorded the v4.1.0 implementation commit hash; implementation, tests, and execution order are unchanged.

- Commit: `4b6ab2b`
- Branch: `feature/long-horizon-workflow`

## [v4.1.2] - 2026-09-04

修正 readiness conformance 日志索引中的提交哈希说明；没有修改实现、测试或执行顺序。

Corrected the readiness conformance changelog index's commit-hash note; implementation, tests, and execution order are unchanged.

- Correct maintenance commit for v4.1.1: `68bacaf`
- Branch: `feature/long-horizon-workflow`

## [v4.0.0] - 2026-09-04

完成 `manipulation.prepare` candidate consumer 的协议加固，并按架构集成、失败路径、权威边界、配置、可维护性五个维度复审通过；保持 Query/no-motion。Hephaestus 仅作为 clean-room 行为参考，未接入其运行时代码。

Hardened the `manipulation.prepare` candidate consumer and passed review across architecture integration, failure paths, authority boundaries, configuration, and maintainability; kept Query/no-motion. Hephaestus was used only as a clean-room behavioral reference, with no runtime code integrated.

### Detailed changes

- `PhyAgentOS/forge/capability_runtime/manipulation_prepare.py`: strict observation/candidate-set identity, duplicate prepared-candidate rejection, provider request isolation, and fail-closed readiness projection.
- `examples/forge-skills/pick-place-workflow/tests/test_manipulation_prepare.py`: revision/frame drift, provider mutation, and duplicate-candidate regression coverage.
- `docs/forge/STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md`, `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md`: implementation status, five-dimension review, execution order, and Hephaestus reference boundary.

### Validation

- Manipulation-prepare tests: `60 passed`; repository tests: `161 passed`; pick-place tests: `256 passed`.
- Ruff, compileall, and `git diff --check` passed.
- No real IK, collision engine, Gateway, Dora, Action executor, hardware, or motion path was started.

## [v4.0.1] - 2026-09-04

回写 v4.0.0 实现提交哈希；没有修改实现、测试或执行顺序。

Recorded the v4.0.0 implementation commit hash; implementation, tests, and execution order are unchanged.

- Commit: `385eb7a`
- Branch: `feature/long-horizon-workflow`

## [v3.10.8] - 2026-09-04

加固 `scene.understand` 对 `scene.observe` identity 与 artifact lineage 的消费边界，并按架构集成、失败路径、权威边界、配置、可维护性五个维度复审通过；保持 Query/no-motion。

Hardened `scene.understand` consumption of `scene.observe` identity and artifact lineage, passing review across architecture integration, failure paths, authority boundaries, configuration, and maintainability; kept Query/no-motion.

### Detailed changes

- `PhyAgentOS/forge/capability_runtime/understanding.py`: strict observation identity, unique artifact/provenance binding, frame consistency, and provider-request isolation.
- `examples/forge-skills/pick-place-workflow/tests/test_scene_understand.py`: binding, provenance, frame-drift, and mutation regression coverage.
- `docs/forge/STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md`, `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md`: stage status and five-dimension review.

### Validation

- Scene-understand tests: `21 passed`; repository tests: `161 passed`; pick-place tests: `250 passed`.
- RoboTwin provider tests: `7 passed, 1 skipped`; Ruff, compileall, and `git diff --check` passed.
- Real model, Gateway/Dora, Action executor, and hardware remain deferred.
- Commit: `2ba3a21` on `feature/long-horizon-workflow`.

## [v3.11.0] - 2026-09-04

加固 `grasp.propose` 对 `scene.understand` geometry artifact 的消费，并按五个维度复审通过；保持 Query/no-motion。

Hardened `grasp.propose` consumption of `scene.understand` geometry artifacts and passed the five-dimension review; kept Query/no-motion.

### Detailed changes

- `PhyAgentOS/forge/capability_runtime/grasp_proposal.py`: strict identity/provenance validation and isolated provider request.
- `examples/forge-skills/pick-place-workflow/tests/test_grasp_propose.py`: binding, provenance, and mutation regressions.
- `docs/forge/STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md`, `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md`: stage status and review.

### Validation

- Grasp proposal tests: `61 passed`; repository: `161 passed`; pick-place: `253 passed`.
- Adapter GraspGen live tests remain blocked by missing optional `numpy`; no live checkpoint claim.
- Commit: `88267b4` on `feature/long-horizon-workflow`.

## [v3.10.2] - 2026-09-04

完成 EnvironmentAdapter/provider-neutral `scene.observe` 核心 seam，并按架构集成、失败路径、权威边界、配置、可维护性五个维度复审通过；保持 no-motion，不连接真实机器人、Dora 或硬件。

Completed the EnvironmentAdapter/provider-neutral `scene.observe` core seam and passed review across architecture integration, failure paths, authority boundaries, configuration, and maintainability; kept no-motion with no real robot, Dora, or hardware connected.

### Detailed changes

- `PhyAgentOS/forge/capability_runtime/observation.py`: explicit provider-neutral ToolSpec, strict observation projection, injected clock, and fail-closed provider/sensor errors.
- `PhyAgentOS/forge/capability_runtime/__init__.py`, `examples/forge-adapters/robotwin20/src/robotwin20_adapter/adapter.py`: core export and sanitized adapter boundary.
- `tests/test_environment_adapter_observation.py`: observation contract, failure, and explicit registration coverage.
- `docs/forge/STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md`, `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md`, `docs/forge/ROBOTWIN_ADAPTER_REFACTOR_DIAGNOSIS.md`: stage status and five-dimension review.

### Validation

- Repository tests: `161 passed`; observation seam: `10 passed`; RoboTwin dependency-free subset: `16 passed`.
- Ruff, compileall, and `git diff --check` passed.
- Full RoboTwin runtime, real Gateway/Dora, geometry consumer, Action executor, and hardware remain deferred.
- Commit: `c46a35a` on `feature/long-horizon-workflow`.
- Follow-up adapter failure-path fix: `69c00d7` on `feature/long-horizon-workflow`.

## [v3.10.0] - 2026-09-04

完成 provider-neutral 抓取放置协议级证据闭环，并按架构集成、失败路径、权威边界、配置、可维护性五个维度复审通过；不连接真实 Action executor、Dora、机器人或硬件。

Completed the provider-neutral protocol-level pick-and-place evidence closure and passed review across architecture integration, failure paths, authority boundaries, configuration, and maintainability; no real Action executor, Dora, robot, or hardware connected.

### Detailed changes

- `examples/forge-skills/pick-place-workflow/src/pick_place_workflow/long_horizon.py:L24-L27,L78-L89,L194-L231,L301-L316`: terminal-response ref extraction, strict acquire identity equality, destination schema, and post-release evidence gate.
- `examples/forge-skills/pick-place-workflow/tests/test_long_horizon.py:L59-L70,L123-L145`: binding-drift, evidence-missing, and terminal-response replay coverage.
- `docs/forge/STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md`, `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md`: stage status and five-dimension review.

### Validation

- Repository tests: `151 passed`; pick-place tests: `245 passed`.
- Ruff, compileall, and `git diff --check` passed.
- Real physical execution and autonomous-evolution promotion remain deferred.
- Commit: `a847cd7` on `feature/long-horizon-workflow`.

## [v3.9.0] - 2026-09-04

完成 Gateway/Dora provider-neutral 无动作 wiring，并按架构集成、失败路径、权威边界、配置、可维护性五个维度完成审查；不连接真实 Dora、Gateway、Action 或硬件。

Completed provider-neutral no-motion Gateway/Dora wiring and reviewed it across architecture integration, failure paths, authority boundaries, configuration, and maintainability; no real Dora, Gateway, Actions, or hardware connected.

### Detailed changes

- `PhyAgentOS/forge/capability_runtime/http_transport.py:L1-L95`: reusable HTTP Gateway transport over `CapabilityRuntime`.
- `PhyAgentOS/forge/capability_runtime/runtime.py:L57-L70,L180-L223,L260-L313`: deadline/unknown and cancel/stop terminal reconciliation; Session timeout rejection.
- `tests/test_gateway_dora_no_motion_conformance.py:L1-L117`: discovery, identity, lifecycle, malformed JSON, cancellation, timeout, and no-POST conformance.
- `docs/forge/STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md`, `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md`: five-dimension acceptance and execution-order clarification.

### Validation

- Repository tests: `150 passed`; pick-place tests: `243 passed`; conformance subset: `11 passed`.
- Ruff, compileall, and `git diff --check` passed.
- Real Dora/Gateway, Action executor, hardware motion, pick-place closure, and autonomous-evolution promotion remain deferred.
- Commit: `dd1ee70` on `feature/long-horizon-workflow`.
- Follow-up log commit: `83185bc`.

## [v3.8.3] - 2026-09-04

完成完整 `gpt-5.6-sol/high` held-out + hazard 真实模型语义评估并关闭 Verification 质量门禁；保留一个 replan/inconclusive 残余质量风险，不连接 Gateway、Dora、Action 或硬件。

Completed the full `gpt-5.6-sol/high` held-out + hazard real-model semantic evaluation and closed the Verification quality gate; retained one replan/inconclusive residual quality risk, with no Gateway, Dora, Action, or hardware connected.

### Detailed changes

- `artifacts/evals/verification/20260904T034715.434600Z-42a21625/run_manifest.json`: full 7-case run bound to commit `2722d78d1f21d43f12c0213811376ee8f8bf57a8`, exact custom provider binding, and redacted file credential source.
- `artifacts/evals/verification/20260904T034715.434600Z-42a21625/metrics.json`: `quality_gate_eligible=true`, `quality_gate_passed=true`, contract/criterion/recovery-context `1.0`, false-positive rate `0`, overall verdict accuracy `0.8571428571428571`.
- `docs/forge/VERIFICATION_MODEL_EVALUATION.md`, `docs/forge/STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md`, `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md`: recorded per-case review, residual replan error, and the next Gateway/Dora no-motion integration stage.

### Validation

- All 7 held-out/hazard cases completed; no credential or Bearer leakage found in artifacts.
- The held-out `replan_required` case was returned as `inconclusive` (`held_out` accuracy `0.75`), above the configured overall `0.8` threshold but retained as follow-up risk.
- Verification gate closure does not authorize physical execution, pick-place closure, or autonomous-evolution promotion.
- Commit: `bccdd6f` on `feature/long-horizon-workflow`.

## [v3.8.2] - 2026-09-04

回写 v3.8.1 实现提交 `9c1b955`，不修改实现或评估行为。

Recorded v3.8.1 implementation commit `9c1b955`; implementation and evaluation behavior were unchanged.

- Commit: `2722d78` on `feature/long-horizon-workflow`.

## [v3.8.1] - 2026-09-04

将独立 key 文件能力接入 `paos agent` 主配置，修正评估文档与日志中的当前状态，并验证 Agent 配置链路。

Wired the independent key-file capability into the `paos agent` main configuration, corrected the evaluation documentation and changelog state, and verified the Agent configuration path.

### Detailed changes

- `PhyAgentOS/config/credentials.py:L1-L48`: strict owner-only, non-symlink API-key-file reader.
- `PhyAgentOS/config/schema.py:L394-L417,L547-L612`, `PhyAgentOS/config/loader.py:L43-L52`, `PhyAgentOS/cli/commands.py:L285-L337,L1650-L1657`: `apiKeyFile` schema, config-path-relative resolution, runtime provider wiring, and status detection.
- `tests/test_config_api_key_file.py:L1-L52`: success, relative-path, dual-source, symlink, and permission regression tests.
- `README.md:L196-L200`, `docs/zh/04-forge-configuration-reference.md:L70-L76`, `docs/forge/VERIFICATION_MODEL_EVALUATION.md:L42-L101`: configuration and execution-order documentation.

### Validation

- `paos status`: `Custom: ✓`.
- No-tool `paos agent` connectivity check completed successfully with `gpt-5.6-sol/high`.
- Repository tests: `147 passed`; Ruff, compileall, and `git diff --check` passed.
- The LiteLLM SOCKS cost-map warning is non-fatal; no Gateway, Dora, Action, hardware, or motion path was started.
- Commit: `9c1b955` on `feature/long-horizon-workflow`.

## [v3.8.0] - 2026-09-04

接入 Verification 真实模型评估的独立 API key 文件，并完成 `gpt-5.6-sol/high` 单 case 连通性验证；同时保持完整 held-out + hazard 门禁、Gateway/Dora 和抓取放置闭环后置。

Added an independent API-key-file credential source for Verification real-model evaluation and completed a `gpt-5.6-sol/high` single-case connectivity check; full held-out + hazard gating, Gateway/Dora, and pick-place closure remain deferred.

### Detailed changes

- `PhyAgentOS/verification/evaluation.py:L6-L18,L137-L190,L254-L329,L514-L548`: strict file credential loading, redaction, and provider binding.
- `PhyAgentOS/verification/service.py:L64-L68`: explicit recovery-context field guidance in the production prompt.
- `evals/verification/evaluation_config_sol_high_v1.json:L1-L25`, `evals/verification/provider.sol_high.example.json:L1-L13`: versioned `custom`/`gpt-5.6-sol` `/v1` configuration with `allow_custom_provider=true` binding.
- `tests/test_verification_model_evaluation.py:L21-L22,L196-L207,L300-L413`, `tests/test_verifier_semantic_conformance.py:L10,L43-L49`: credential, prompt, and strict-schema regression coverage.
- `docs/forge/VERIFICATION_MODEL_EVALUATION.md:L42-L101`, `docs/forge/STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md:L272-L285`: operating instructions and evidence boundaries.

### Validation

- `gpt-5.6-sol/high --max-cases 1`: completed with contract/verdict/criterion/recovery-context `1.0`; gate eligibility remains `false`.
- Full repository regression after the follow-up configuration wiring: `147 passed`; Ruff, compileall, and `git diff --check` passed.
- No Gateway, Dora, Action, hardware, or motion path was started.

## [v3.7.2] - 2026-09-04

回写 v3.7.1 审计维护提交；没有修改实现、评估配置、运行证据或执行顺序。

Recorded the v3.7.1 audit-maintenance commit; implementation, evaluation configuration, run evidence, and execution order are unchanged.

- Commit: `d88fd3a`
- Branch: `feature/long-horizon-workflow`

## [v3.7.1] - 2026-09-04

维护 v3.7.0 审计记录：回写实现提交，并把真实模型 blocker 更新为提交后的终态 preflight 产物；没有修改评估行为、阈值或执行顺序。

Maintained the v3.7.0 audit record by recording the implementation commit and updating the real-model blocker to the terminal post-commit preflight artifact; evaluation behavior, thresholds, and execution order are unchanged.

- Implementation commit: `8775073`
- Post-commit blocked run: `artifacts/evals/verification/20260903T163926.458050Z-db095983/`
- The manifest binds the run to full commit `8775073eccb26791a5ffd0215794c49fd46f3f82`; no model request or quality score was produced.

## [v3.7.0] - 2026-09-03

建立可复现的 Verification Service 真实模型语义质量评估基础设施，并在代码审查后关闭跨层依赖、非终态错误、fixture 身份冒充和部分 case 误过完整门禁的问题。真实模型凭据当前不可用，因此质量门禁保持 blocked；未连接 Gateway、Dora、Action 或硬件。

Established reproducible real-model semantic-quality evaluation infrastructure for Verification Service, then closed reverse-layer dependencies, non-terminal errors, fixture identity masquerading, and partial-case gate bypasses during code review. Real-model credentials remain unavailable, so the quality gate is blocked; no Gateway, Dora, Action, or hardware was connected.

### Detailed changes

- `PhyAgentOS/verification/evaluation.py:L1-L675`: adds strict dataset/config/provider schemas, immutable provider gate binding, unique UTC run directories, provenance/digests, production subprocess execution, fsynced per-attempt records, metrics, threshold decisions, and terminal blocked/error artifacts.
- `PhyAgentOS/verification/validation.py:L1-L34`, `PhyAgentOS/agent/session_verifier.py:L29-L32,L178-L192`: moves criteria/evidence-reference authority validation into the Verification layer while preserving the Agent-facing error contract.
- `PhyAgentOS/verification/request_builder.py:L35-L52,L389`: shares the production verification prompt envelope with the evaluator.
- `scripts/evaluate_verification_model.py:L1-L37`, `evals/verification/semantic_verifier_v1.json:L1-L299`, `evals/verification/evaluation_config_v1.json:L1-L23`, `evals/verification/provider.openai_codex.example.json:L1-L11`: adds the CLI, 10-case development/held-out/hazard corpus, thresholds, and credential-safe provider example.
- `tests/test_verification_model_evaluation.py:L1-L449`: covers strict loading, production subprocess fixture replay, credential blockers, terminal startup errors, provider identity binding, and partial-case ineligibility.
- `docs/forge/VERIFICATION_MODEL_EVALUATION.md:L1-L75`, `docs/forge/STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md:L214-L250`, `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L315-L320`: records the quality/evaluation boundary and preserves the approved execution order.

### Key diff

```text
Before: fixture smoke and partial runs could self-declare real_model eligibility; evaluation reused an Agent-private validator; startup failure could leave a running manifest.
After:  a versioned non-custom provider identity and full case set are mandatory; validation is owned by Verification; every blocked/error path writes terminal fail-closed artifacts.
```

### Validation

- Verification/evaluation focused suite: `57 passed`.
- Repository suite: `136 passed`.
- Pick-place workflow and RoboTwin adapter suites: `310 passed` using the existing PAOS packages plus system NumPy; the unmodified PAOS environment alone currently lacks NumPy.
- Ruff, compileall, `git diff --check`, reverse-dependency scan, and credential/artifact review passed.
- Real-model preflight remains blocked by unavailable Codex OAuth credentials; fixture metrics are explicitly not quality-gate evidence.

Git commit: `8775073` on `feature/long-horizon-workflow`.

## [v3.6.0] - 2026-09-03

完成真实 `VerificationServiceProcess` provider-spec 子进程门禁：父进程启动正式子进程，独立 OpenAI-compatible HTTP stub 验证配置传递、私有 readiness、鉴权请求、结构化 verdict、provider 失败、超时和 stop 清理；未连接外部模型、Gateway、Watchdog、Action 或硬件。

Completed the production `VerificationServiceProcess` provider-spec subprocess gate: the parent starts the formal child process, and an independent OpenAI-compatible HTTP stub verifies config transfer, private readiness, authenticated requests, structured verdicts, provider failure, timeout, and stop cleanup; no external model, Gateway, Watchdog, Action, or hardware was connected.

### Detailed changes

- `PhyAgentOS/verification/service.py:L28,L282-L314,L405-L418`: added a stable service identifier and token-protected `/readyz` readiness probe with strict JSON/service identity checks; retained `/healthz` as liveness.
- `tests/test_verification_service_process.py:L1-L230`: covers formal subprocess startup, provider-spec propagation, external HTTP provider stub, failure/timeout mapping, readiness authentication, and process cleanup.
- `docs/forge/STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md:L161-L212`: records implementation review, validation evidence, and remaining gates.

### Validation

- Repository tests: `127 passed`.
- Pick-place example tests: `241 passed`.
- Ruff, compileall, and `git diff --check` passed.
- Real-model semantic quality, Gateway/Dora wiring, and pick-place closure remain pending.

Git commit: `cfef665` on `feature/long-horizon-workflow`.

## [v3.6.1] - 2026-09-03

维护 v3.6.0 实现提交日志，记录 provider-spec 子进程门禁提交 hash。

Maintained the v3.6.0 implementation log and recorded the provider-spec subprocess gate commit hash.

Git commit: `cfef665` on `feature/long-horizon-workflow`.

## [v3.5.2] - 2026-09-03

维护提交日志：回写 v3.5.0/v3.5.1 的实现提交 hash，并核对当前分支。

Commit-log maintenance: recorded the implementation commit hash for v3.5.0/v3.5.1 and verified the current branch.

- Implementation commit: `e4cdac5`
- Branch: `feature/long-horizon-workflow`

## [v3.5.1] - 2026-09-03

完成第三轮五维代码审查并修复 Store、状态协议和 Verification HTTP 边界；未启动真实 provider、外部模型、Gateway、Action 或硬件。

Completed the third five-dimension code review and fixed Store, state-protocol, and Verification HTTP boundaries; no real provider, external model, Gateway, Action, or hardware was started.

Git commit: `e4cdac5` on `feature/long-horizon-workflow`.

### Detailed changes

- `PhyAgentOS/forge/task.py:L83-L125,L182-L262,L381-L411,L417-L463,L571-L586`：finite execution/event payload、完整聚合关系校验、create/update pre-commit validation、`task_id`/`created_at`/origin identity immutability。
- `PhyAgentOS/state_io/protocol.py:L31-L55,L140-L155`：JSON/YAML duplicate-key rejection。
- `PhyAgentOS/verification/service.py:L33-L51,L197-L239,L341-L351,L372-L421`：strict JSON decoding and strict parent constructor types。
- `tests/test_state_file_authority_boundaries.py`、`tests/test_state_file_adapter.py`、`tests/test_verification_service_replay.py`、`tests/test_verification_service_config.py`：真实边界回归覆盖。
- `docs/forge/STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md:L117-L176`：第三轮 review 记录。

### Validation

- Repository tests: `123 passed`.
- Pick-place example tests: `241 passed`.
- Ruff, compileall, and `git diff --check` passed.
- Provider-spec production subprocess, real-model semantic quality, and pick-place closure remain pending.

## [v3.5.0] - 2026-09-03

完成状态文件适配、Evidence、Verifier 与 Verification Service 的边界修复，并完成第二轮代码审查；未启动真实 provider 子进程、外部模型、Gateway、Watchdog、Action 或硬件。

Completed boundary fixes for state-file adapters, Evidence, Verifier, and Verification Service, followed by a second code review; no real provider subprocess, external model, Gateway, Watchdog, Action, or hardware was started.

### Detailed changes

- `PhyAgentOS/forge/task.py:L45-L56,L190-L244,L286-L361,L393-L445,L1193-L1240`：AgentTask approval binding、SQLite origin migration/backfill/index、immutable origin、full aggregate revalidation、terminal retention wiring。
- `PhyAgentOS/state_io/adapters.py:L275-L322,L390-L405,L429-L510,L548-L632`：strict TARGETS/SESSIONS schema、bounded promotion、dedup exception handling。
- `PhyAgentOS/forge/evidence.py:L31-L115,L118-L152,L165-L244,L301-L350,L570-L583`：v2 manifest、writer-owned path、pre-write immutability、strict robot-state JSON、stable bundle identity。
- `PhyAgentOS/verification/request_builder.py:L27-L32,L198-L227,L253-L318`：AgentTask Bundle binding, same-bundle evidence ownership, strict structured JSON and unique paths。
- `PhyAgentOS/verification/service.py:L56-L206,L345-L418`、`PhyAgentOS/config/schema.py:L341-L361`：shared provider/service schema and stable HTTP errors。
- `PhyAgentOS/state_io/__init__.py`：移除无生产 owner 的 generic SKILLRUNTIME/LESSONS renderer 公共导出。
- `tests/test_state_file_authority_boundaries.py:L1-L476`：真实 Store/writer/request/context/retention 边界审查覆盖。
- `docs/forge/STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md:L1-L176`：完整审查发现、修复记录和三轮五维复审结论。

### Key diff

```text
Before: origin migration was incomplete; malformed evidence/provider failures could cross owner boundaries; generic renderers looked production-ready.
After:  origins migrate and remain immutable; evidence/provider requests fail closed; only owned projections are represented as implemented.
```

### Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -q tests` → `105 passed`.
- Pick-place example suite → `241 passed`.
- Unguarded pytest is blocked before collection by the system ROS `launch_testing` plugin missing `lark`; validation isolates plugins and explicitly loads `pytest_asyncio.plugin`.
- Ruff, compileall, and `git diff --check` passed.
- Provider-spec production subprocess, real-model semantic quality, and pick-place closure remain pending.

## [v3.4.6] - 2026-09-03

增加 Verification Service HTTP replay/failure conformance：验证授权 token、请求 envelope、重复 replay、
deterministic provider verdict、invalid-response normalization 和 provider failure。测试仅使用进程内
provider，不启动生产验证子进程或连接外部模型。

Added Verification Service HTTP replay/failure conformance for authorization tokens, request envelopes, repeated
replay, deterministic provider verdicts, invalid-response normalization, and provider failures. Tests use only an
in-process provider and do not start the production verification subprocess or connect to external models.

### Detailed changes

- `tests/test_verification_service_replay.py:L1-L117` adds HTTP handler/engine replay and failure tests.
- `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L285-L296` records service-level conformance and remaining provider-spec/real-model gates.
- `docs/forge/STATE_FILE_ADAPTER_FEATURE_CARD.md:L60-L63` records Verification Service HTTP conformance coverage.

### Key diff

```text
Before: verifier checks were tested locally, but the HTTP service boundary had no deterministic replay matrix.
After:  the real handler + VerificationEngine path validates auth, request schema, normalization, replay, and failure propagation without external side effects.
```

### Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests` → `58 passed`.
- Ruff, compileall, and `git diff --check` passed.
- No production Verification Service, external model, Gateway, Watchdog, Action, or motion authorization was used.

## [v3.4.5] - 2026-09-03

增加 ForgeTaskVerifier 本地 verdict contract conformance：success/replan 不变量、criteria 精确绑定、
unknown evidence、malformed response 和 no-service 边界。该轮不启动 Verification Service，不调用模型或 Gateway。

Added local ForgeTaskVerifier verdict contract conformance for success/replan invariants, exact criterion binding,
unknown evidence, malformed responses, and the no-service boundary. This iteration does not start the Verification
Service or call a model or Gateway.

### Detailed changes

- `tests/test_verifier_semantic_conformance.py:L1-L126` adds deterministic verifier acceptance/rejection tests.
- `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L280-L290` distinguishes local verdict contract checks from provider-backed semantic quality.
- `docs/forge/STATE_FILE_ADAPTER_FEATURE_CARD.md:L59-L62` records local verifier conformance coverage.

### Key diff

```text
Before: verifier boundary tests covered projection-as-evidence rejection, but not the full verdict contract matrix.
After:  deterministic fixtures validate criteria/evidence/recovery invariants and malformed responses without starting a service.
```

### Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests` → `54 passed`.
- Ruff, compileall, and `git diff --check` passed.
- No Verification Service, model, Gateway, Watchdog, Action, or motion authorization was used.

## [v3.4.4] - 2026-09-03

校正执行顺序文档：明确 `SKILLRUNTIME.md`/`LESSONS.md` 是可选 projection，记录受限 promotion 先于
后续 replay conformance 的历史顺序，并确认抓取放置和自主进化尚未启动。未修改运行时代码。

Corrected execution-order documentation: `SKILLRUNTIME.md`/`LESSONS.md` are optional projections, the historical
ordering of bounded promotion before later replay conformance is recorded, and pick-place plus autonomous evolution
remain unstarted. No runtime code was changed.

### Detailed changes

- `docs/forge/ROBOTWIN_ADAPTER_REFACTOR_DIAGNOSIS.md:L400-L420` aligns required versus optional file adapters and records the bounded-promotion ordering review.
- `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L275-L283` distinguishes request-level Evidence conformance from remaining semantic/live replay work.

### Validation

- Documentation-only change; `git diff --check` passed.
- No Gateway, Watchdog, Action, AgentTask, or motion authorization was used.

## [v3.4.3] - 2026-09-03

增加 Evidence request-level conformance：不可变 Evidence Bundle 在跨工作区 replay 时重新校验
capture window、必需 kind/source、association、retention、digest/size、媒体类型和结构化 JSON。
该轮不修改 Verifier 语义权威逻辑，也不把 `ENVIRONMENT.md` 变成 Evidence。

Added Evidence request-level conformance: immutable Evidence Bundles are revalidated across workspace replay
for capture windows, required kind/source, association, retention, digest/size, media type, and structured JSON.
This iteration does not change Verifier semantic authority or turn `ENVIRONMENT.md` into Evidence.

### Detailed changes

- `tests/test_evidence_semantic_replay_conformance.py:L1-L184` adds immutable bundle replay and fail-closed request validation tests.
- `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L280-L287` records request-level Evidence conformance and its remaining limits.
- `docs/forge/STATE_FILE_ADAPTER_FEATURE_CARD.md:L59-L61` records Evidence request conformance coverage.

### Key diff

```text
Before: Evidence boundary had basic projection rejection but no dedicated replay matrix for request consumption.
After:  immutable bundle replay validates identity, window, policy, retention, digest/size, media, and structured data;
        LLM semantic verdict and live Gateway replay remain explicitly out of scope.
```

### Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests` → `48 passed`.
- `PYTHONPATH=examples/forge-skills/pick-place-workflow/src python -m pytest -q examples/forge-skills/pick-place-workflow/tests` → `241 passed`.
- Ruff, compileall, and `git diff --check` passed.
- No real Gateway, Watchdog, Action, or motion authorization was used.

## [v3.4.2] - 2026-09-03

增加状态文件适配的 replay/failure conformance：跨工作区回放保持确定性，未知字段在触及 Store/Gateway
前 fail-closed，Store 编译失败不留下生命周期残留，projection drift 保留原内容，TARGETS/SESSIONS
继续保持 `motion_authorized=false`。`SKILLRUNTIME.md` 与 `LESSONS.md` producer 仍明确为可选 projection。

Added state-file adapter replay/failure conformance: cross-workspace replay remains deterministic, unknown fields
fail closed before Store/Gateway access, Store compilation failures leave no lifecycle residue, projection drift
preserves the prior content, and TARGETS/SESSIONS retain `motion_authorized=false`. `SKILLRUNTIME.md` and
`LESSONS.md` producers remain explicitly optional projections.

### Detailed changes

- `tests/test_state_file_replay_conformance.py:L1-L215` adds replay, Fake Store failure, Gateway no-call sentinel, drift-preservation, and no-motion tests.
- `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L280-L288` separates required Phase-B boundary conformance from optional Markdown projections.

### Key diff

```text
Before: replay/failure coverage was distributed across adapter tests without an explicit cross-workspace boundary.
After: dedicated conformance tests assert deterministic replay, no partial lifecycle state, drift preservation,
       and no-motion behavior while keeping Markdown non-authoritative.
```

### Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests` → `43 passed`.
- `PYTHONPATH=examples/forge-skills/pick-place-workflow/src python -m pytest -q examples/forge-skills/pick-place-workflow/tests` → `241 passed`.
- Ruff, compileall, and `git diff --check` passed.
- No real Gateway, Watchdog, Action, or motion authorization was used.

## [v3.4.1] - 2026-09-03

增加 Verifier/Evidence boundary conformance：`ENVIRONMENT.md` projection 不能被解析为 Evidence Bundle，
verifier verdict 不能以 projection URI 冒充 evidence reference。未修改 Verifier 的事实源或语义判定逻辑。

Added Verifier/Evidence boundary conformance proving that an `ENVIRONMENT.md` projection cannot be parsed as an
Evidence Bundle and a verifier verdict cannot use a projection URI as an evidence reference. No verifier fact
source or semantic decision logic was changed.

### Detailed changes

- `tests/test_verifier_evidence_boundary.py:L1-L59` adds projection-as-evidence rejection and unknown projection-reference verdict tests.
- `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L271-L283` records the completed boundary conformance and remaining full semantic/replay work.

### Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests` → `38 passed`.
- Ruff, compileall, and `git diff --check` passed.
- No Gateway, Watchdog, Action, AgentTask, or motion authorization was produced.

## [v3.4.0] - 2026-09-03

增加 `ForgeEvidenceWriter` 到 `EnvironmentProjectionProducer` 的受限关联。writer 校验自身生成的
before/after manifest、phase 和路径，生成稳定 opaque `evidence://` reference，并拒绝同一 phase 的
不同内容覆盖；producer 可自动注入 phase/reference 并拒绝不匹配值。Evidence/Verifier 仍是权威，未增加
Gateway、Watchdog、Action、AgentTask 或运动路径。

Added a bounded association from `ForgeEvidenceWriter` to `EnvironmentProjectionProducer`. The writer validates
its before/after manifests, phase, and path, derives a stable opaque `evidence://` reference, and rejects content
replacement within a phase. The producer injects phase/reference or rejects mismatches. Evidence/Verifier remain
authoritative; no Gateway, Watchdog, Action, AgentTask, or motion path was added.

### Detailed changes

- `PhyAgentOS/forge/evidence.py:L27-L143` adds writer-owned snapshot identity validation, stable evidence URI derivation, and same-phase immutability checks.
- `PhyAgentOS/forge/environment_projection.py:L30-L237` adds `publish_from_evidence_writer()` and the minimal `EvidenceSnapshotStore` seam.
- `PhyAgentOS/forge/__init__.py:L3-L33` exports the evidence association protocol.
- `tests/test_environment_projection_producer.py:L1-L194` covers manifest association, stable URI, overwrite rejection, phase/reference mismatch, and non-writer paths.
- `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L265-L278` and `docs/forge/STATE_FILE_ADAPTER_FEATURE_CARD.md:L27-L71` record the completed association and remaining Phase-B work.

### Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests` → `36 passed`.
- `PYTHONPATH=examples/forge-skills/pick-place-workflow/src python -m pytest -q examples/forge-skills/pick-place-workflow/tests` → `241 passed`.
- Ruff, compileall, and `git diff --check` passed.
- Full RoboTwin collection remains environment-limited by missing `numpy`/package path; no motion or live verifier run.

## [v3.3.0] - 2026-09-03

增加受限 `EnvironmentProjectionProducer`：从已捕获的 `ObservationSnapshot` 和显式 provenance 生成严格
`ENVIRONMENT.md` projection；before/after 快照必须绑定 `evidence://` URI，可选地与
`EnvironmentAdapter.snapshot()` 的 scene revision 一致性校验。producer 只做原子 projection 写入，
不调用 Gateway、Watchdog、Action，不创建 AgentTask，也不替代 Evidence/Verifier 事实源。

Added a bounded `EnvironmentProjectionProducer` that renders a strict `ENVIRONMENT.md` projection from an
already captured `ObservationSnapshot` and explicit provenance. Before/after snapshots must use an `evidence://`
URI and can be revision-bound to `EnvironmentAdapter.snapshot()`. The producer only performs atomic projection
writes; it does not call Gateway, Watchdog, or Action, create AgentTasks, or replace Evidence/Verifier authority.

### Detailed changes

- `PhyAgentOS/forge/environment_projection.py:L1-L180` adds the producer input contract, adapter revision binding, evidence URI gate, and no-side-effect projection path.
- `PhyAgentOS/forge/__init__.py:L3-L31` exports the producer API.
- `PhyAgentOS/state_io/adapters.py:L553-L601` forwards optional `expected_sha256` to the atomic projection writer.
- `tests/test_environment_projection_producer.py:L1-L144` covers before/after success, idempotency, drift, invalid/empty input, evidence URI, adapter revision, and no-capture boundaries.
- `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L256-L273` and `docs/forge/STATE_FILE_ADAPTER_FEATURE_CARD.md:L27-L71` record the producer boundary and remaining Phase-B work.

### Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests` → `33 passed`.
- Ruff, compileall, and `git diff --check` passed.
- No live pick-place provider, Gateway invocation, AgentTask, Evidence verdict, or motion authorization was produced.

## [v3.2.0] - 2026-09-03

完成 `ENVIRONMENT.md` 的严格 projection 适配：增加 snapshot/provenance schema、revision 一致性校验，
将 SceneGraph 查询从宽松 loader 切换为严格 parser，并同步模板。缺失、旧版或损坏文件现在返回 bounded
error；Evidence snapshot 仍是唯一语义事实源，未接入动作、Watchdog、Gateway 或硬件。

Completed strict `ENVIRONMENT.md` projection adaptation with snapshot/provenance schema and revision consistency
checks, switched SceneGraph queries from the permissive loader to the strict parser, and aligned the template.
Missing, legacy, or damaged files now return a bounded error. Evidence snapshots remain the sole semantic authority;
no Action, Watchdog, Gateway, or hardware path was added.

### Detailed changes

- `PhyAgentOS/state_io/adapters.py:L88-L148,L330-L344,L563-L574` adds the strict environment schema, parser, and renderer validation.
- `PhyAgentOS/agent/tools/scene_graph.py:L11-L63` consumes only valid environment projections and rejects malformed input.
- `PhyAgentOS/templates/ENVIRONMENT.md:L1-L34` aligns the template with `paos.state-file.v1`.
- `tests/test_state_file_adapter.py:L264-L335,L406-L414` covers provenance, revision, legacy, and fail-closed behavior.

### Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests` → `26 passed`.
- `ruff check ...`, `python -m compileall ...`, and `git diff --check` passed.

## [v3.1.1] - 2026-09-03

完成最近三个 `TARGETS.md` candidate 功能的代码审查与测试。修复 `profile_id` 可包含路径分隔符的问题，
并补充审批 decision/时间戳、非法 profile、baseline 差异批准、输入文件不变和 no-motion 测试。

Completed code review and testing for the three recent `TARGETS.md` candidate features. Fixed path-like
`profile_id` identities and added coverage for approval decision/timestamp, invalid profiles, explicit baseline
differences, input immutability, and no-motion behavior.

### Detailed changes

- `PhyAgentOS/state_io/adapters.py:L180-L190` now rejects path-unsafe `profile_id` values.
- `tests/test_state_file_adapter.py:L82-L180` adds the review and failure-path tests; 18 focused tests pass.
- `docs/forge/STATE_FILE_ADAPTER_FEATURE_CARD.md:L50-L56` and `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L246-L255` record the review result and remaining Minor risk.

### Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_state_file_adapter.py` → `18 passed`.
- `ruff check ...`, `python -m compileall ...`, and `git diff --check` passed.

## [v3.1.0] - 2026-09-03

新增 `TARGETS.md` 的已验证 Capability Profile candidate：候选必须通过严格 shadow validation，并由
`TargetProfileApproval` 同时绑定源文件 digest 与 baseline digest。candidate 仅用于比较和回放，固定
`motion_authorized=false`，不写 Runtime/Profile 权威配置，不改变 Action admission 或运动限幅。

Added a validated Capability Profile candidate for `TARGETS.md`: candidates must pass strict shadow validation
and carry a `TargetProfileApproval` bound to both source and baseline digests. Candidates are limited to comparison
and replay, always expose `motion_authorized=false`, and cannot write Runtime/Profile authorities or alter Action
admission or motion limits.

### Detailed changes

- `PhyAgentOS/state_io/adapters.py:L24-L145,L253-L300` adds `TargetProfileApproval`, `TargetProfileCandidate`, and `promote_targets_candidate()`.
- `PhyAgentOS/state_io/__init__.py:L3-L42` exports the bounded candidate API.
- `tests/test_state_file_adapter.py:L61-L130` covers approved candidates, baseline drift, and no-motion behavior.
- `docs/forge/STATE_FILE_ADAPTER_FEATURE_CARD.md:L24-L47` and `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L240-L247` document the non-admission boundary.

### Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_state_file_adapter.py` → `15 passed`.
- `ruff check ...`, `python -m compileall ...`, and `git diff --check` passed.

## [v3.0.0] - 2026-09-03

在人工确认边界内提升 `SESSIONS.md` 输入：新增 digest 绑定审批凭据、单会话幂等编译器，并通过
`AgentTaskCoordinator.create_task()` 写入既有 AgentTask SQLite 事实源；新增 `parent_task_id` 与
`retry_limit` 声明式字段。编译前检查全局非终态任务，重复编译复用既有记录；不直接写 SQLite、不调度
Watchdog、不调用 Gateway、不授权运动。

Promoted `SESSIONS.md` within an explicit human-approval boundary: added digest-bound approval credentials,
single-session idempotent compilation, and writes through the existing `AgentTaskCoordinator.create_task()`
to the AgentTask SQLite authority. Added declarative `parent_task_id` and `retry_limit` fields. Compilation
checks the global non-terminal slot and reuses repeated source/session records; it does not write SQLite directly,
dispatch Watchdog, call Gateway, or authorize motion.

### Detailed changes

- `PhyAgentOS/state_io/adapters.py:L43-L372` adds approval validation, one-session compiler, stable origin identity, parent/active-task checks, and no-motion result semantics.
- `PhyAgentOS/forge/task.py:L153-L181,L300-L315,L420-L527` persists optional parent/retry metadata and adds origin-key lookup used for idempotency.
- `PhyAgentOS/state_io/__init__.py:L3-L39` exports the bounded promotion API.
- `tests/test_state_file_adapter.py:L207-L322` covers approval digest binding, idempotent reuse, active-task and multi-session conflicts, unknown parents, and no-motion.
- `docs/forge/STATE_FILE_ADAPTER_FEATURE_CARD.md:L6-L58` and `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L228-L244` record the promotion boundary and remaining non-goals.

### Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_state_file_adapter.py` → `13 passed`.
- `ruff check PhyAgentOS/state_io PhyAgentOS/forge/task.py tests/test_state_file_adapter.py` passed.
- `python -m compileall -q PhyAgentOS/state_io PhyAgentOS/forge/task.py tests/test_state_file_adapter.py` and `git diff --check` passed.
- Existing pick-place task tests remain un-runnable in this environment because `pick_place_workflow` is not on `PYTHONPATH`; this is reported separately and is not treated as a pass.

## [v2.9.0] - 2026-09-03

新增 PAOS 状态文件架构诊断文档，汇总 `TARGETS.md`、`SKILLRUNTIME.md`、`SESSIONS.md`、
`ENVIRONMENT.md`、`LESSONS.md` 与现有 AgentTask、Gateway、Evidence、Runtime 和 Experience
权威边界的对应关系；明确 Markdown 不是事务性中间状态的唯一事实源，并提出“先冻结最小上层契约，
再继续抓取放置证据闭环，最后实现文件输入/投影适配”的审核方向。

Added the PAOS state-file architecture diagnosis documenting how `TARGETS.md`, `SKILLRUNTIME.md`,
`SESSIONS.md`, `ENVIRONMENT.md`, and `LESSONS.md` map to the existing AgentTask, Gateway, Evidence,
Runtime, and Experience authorities. It clarifies that Markdown is not the sole source of transactional
intermediate state and proposes “freeze the minimal upper-layer contract, continue the pick-place evidence
closure, then add file input/projection adapters” for review.

### Detailed changes

- `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L1-L240` adds the bilingual-domain diagnosis, authority table, Markdown input/projection protocol, pick-place impact analysis, autonomous-evolution boundaries, and six review gates.
- `docs/forge/ROBOTWIN_ADAPTER_REFACTOR_DIAGNOSIS.md:L390-L411` records the state-file protocol decision and preserves the provider-neutral pick-place implementation order.
- `docs/README.md:L29,L63` adds Chinese and English index links to the diagnosis.
- `changelog/2026-09_part2.md:L1-L61` records the detailed bilingual change, actual line ranges, key diffs, and validation in the split monthly archive.

### Validation

- `git diff --check` passed.
- Markdown headings, cross-document links, line references, and bilingual changelog entries were inspected.
- No source code, runtime behavior, or execution contract was changed by this documentation decision.

## [v2.9.1] - 2026-09-03

审核并确认“先做受限文件适配、后做抓取放置闭环”符合 PAOS 扩展原则。执行顺序调整为：冻结最小上层与文件契约，
实现只读 projection、`TARGETS.md` shadow validation、`SESSIONS.md` dry-run 及回放验证，人工确认后再提升输入边界，
最后推进抓取放置和受控自主进化。适配层不得拥有 Watchdog、AgentTask 生命周期、Gateway 或 Action admission，
也不得建立 Markdown queue Runtime。

Reviewed and confirmed that “restricted file adapters before the pick-place closure” conforms to PAOS extension principles.
The execution order now freezes the minimal upper-layer and file contracts, implements read-only projections,
`TARGETS.md` shadow validation, `SESSIONS.md` dry-runs, and replay validation, promotes inputs only after human approval,
and then advances pick-place and guarded evolution. Adapters do not own Watchdog, AgentTask lifecycle, Gateway, or Action
admission, and no Markdown queue Runtime is introduced.

### Detailed changes

- `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L162-L208,L249-L257` records the review conclusion and revised five-stage order.
- `docs/forge/ROBOTWIN_ADAPTER_REFACTOR_DIAGNOSIS.md:L398-L414` synchronizes the RoboTwin execution order and explicitly approves restricted file adapters first.
- `changelog/2026-09_part2.md:L55-L103` records the bilingual plan, actual changes, validation, and commit references.

### Validation

- `git diff --check` passed.
- PAOS extension principles were checked against ownership, provider-neutral boundary, no-second-protocol, projection authority, and no-motion requirements.
- No source code, runtime behavior, hardware IO, or motion authorization changed.

## [v2.10.0] - 2026-09-03

新增 PAOS State File Adapter 第一阶段实现：严格解析 `paos.state-file.v1` Markdown 结构化区块，提供原子 projection 写入、canonical digest drift 检查、`TARGETS.md` capability shadow validation、`SESSIONS.md` 确定性 dry-run 预览，并通过功能引用卡固定其非执行边界。该适配器不写入 AgentTask 生命周期、不调度 Watchdog、不调用 Gateway，也不授权运动。

Added the phase-one PAOS State File Adapter: strict `paos.state-file.v1` Markdown block parsing, atomic projection writes, canonical-digest drift checks, `TARGETS.md` capability shadow validation, and deterministic `SESSIONS.md` dry-run previews. The feature card fixes its non-execution boundary: it does not write AgentTask lifecycle state, schedule Watchdog work, call Gateway, or authorize motion.

### Detailed changes

- `PhyAgentOS/state_io/protocol.py:L1-L224` adds the strict envelope parser, opaque-reference metadata validation, canonical digest, atomic projection writer, and explicit drift error.
- `PhyAgentOS/state_io/adapters.py:L1-L214` adds target shadow validation, deterministic session previews, and projection entry points for Runtime, Environment, and Lessons.
- `PhyAgentOS/state_io/__init__.py:L1-L35` exports the bounded adapter API without adding a Gateway or Runtime route.
- `tests/test_state_file_adapter.py:L1-L198` covers valid/invalid envelopes, limits, drift, projection mode, deterministic dry-run, duplicate/unsafe identities, and no-motion flags.
- `docs/forge/STATE_FILE_ADAPTER_FEATURE_CARD.md:L1-L61` records the normative references, ownership, failure semantics, acceptance gates, and non-goals.
- `docs/forge/PAOS_STATE_FILE_ARCHITECTURE_DIAGNOSIS.md:L162-L228` records the phase-one implementation status and next promotion gate; `docs/README.md:L30,L65` indexes the feature card.

### Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_state_file_adapter.py` → `9 passed`.
- `ruff check PhyAgentOS/state_io tests/test_state_file_adapter.py` passed.
- `python -m compileall -q PhyAgentOS/state_io tests/test_state_file_adapter.py` passed.
- `git diff --check` passed.
- No hardware, simulator, Gateway, Watchdog, AgentTask store, or motion path was invoked.

## [v2.8.17] - 2026-09-03

Implemented the provider-neutral grasp proposal extension: `grasp.propose`
targets may carry observation/revision/frame/calibration-bound geometry
artifacts, while the independent adapter resolves point clouds and invokes an
isolated GraspGen-compatible JSONL worker. Candidate matrices are validated,
converted to normalized pose/approach evidence, filtered with deterministic
SE(3) NMS, and returned with a reconciled funnel; no IK, collision admission,
or motion authorization is added.

实现 provider-neutral 抓取候选扩展：`grasp.propose` target 可携带绑定
observation/revision/frame/calibration 的几何资产；独立 adapter 解析点云并调用隔离的
GraspGen-compatible JSONL worker，校验候选矩阵、转换为归一化位姿/approach 证据，执行确定性
SE(3) NMS 并返回闭合 funnel；没有增加 IK、碰撞准入或运动授权。

### Detailed changes

- `PhyAgentOS/forge/capability_runtime/grasp_proposal.py:L34-L678` adds neutral geometry-artifact binding, mapping normalization, unit quaternion/approach validation, and strict fail-closed projection.
- `examples/forge-adapters/robotwin20/src/robotwin20_adapter/grasp_proposal.py:L1-L383` adds point-cloud resolution, isolated worker request/response mapping, candidate canonicalization, NMS, provenance, and cleanup handling.
- `examples/forge-adapters/robotwin20/runtime/graspgen_worker.py:L1-L129` and `runtime/worker_protocol.py:L12-L72` add the isolated worker entrypoint and versioned JSONL lifecycle.
- `examples/forge-adapters/robotwin20/src/robotwin20_adapter/grasp_profile.py:L1-L75` and `profiles/robotwin20/graspgen.yaml:L1-L29` keep interpreter, checkpoint, and filtering settings outside PAOS.
- `examples/forge-skills/pick-place-workflow/contracts/grasp.propose.tool.yaml:L1-L110` mirrors the public ToolSpec; tests cover mapping normalization, artifact binding, NMS, malformed worker data, and cleanup failure.

### Validation

- Generic PAOS grasp conformance: `57 passed`.
- Isolated adapter grasp/provider/profile tests: `7 passed`.
- Ruff, compileall, and `git diff --check` passed.
- Live GraspGen inference was not claimed: no verified local checkpoint/source environment was found; the worker reports unavailable until an external profile supplies them.
- `.codegraph/` and `.cursor/` remain untracked and are not staged.

## [v2.8.16] - 2026-09-03

Implemented the clean-room, adapter-side single-view perception composition:
semantic entity binding to LocateAnything proposals, bounded proposal-worker
shutdown, SAM2 box segmentation in its separate environment, deterministic
RGB-D localization, transactional derived artifacts, and projection through
the existing provider-neutral `scene.understand` Gateway contract. PAOS and
RoboTwin20 remain free of model-environment dependencies, and every result is
Query evidence with `motion_authorized=false`.

实现 clean-room、adapter-side 单视角感知 composition：语义实体绑定
LocateAnything proposal，关闭 proposal worker 后再在独立环境运行 SAM2 box
segmentation，然后确定性生成 RGB-D 定位和事务式派生资产，最终通过既有
provider-neutral `scene.understand` Gateway 契约投影。PAOS 和 RoboTwin20 不引入模型
环境依赖，所有结果仍是 `motion_authorized=false` 的 Query 证据。

### Detailed changes

- `PhyAgentOS/forge/capability_runtime/understanding.py:L461-L601` binds every derived artifact to the current request's observation, revision, frame, and calibration.
- `examples/forge-adapters/robotwin20/src/robotwin20_adapter/single_view_perception.py:L1-L707` composes proposal, segmentation, localization, artifact materialization, rollback, and ambiguity handling.
- `examples/forge-adapters/robotwin20/src/robotwin20_adapter/process_worker.py:L1-L212` and `perception_profile.py:L1-L153` add bounded JSONL process lifecycle and profile-only environment wiring.
- `examples/forge-adapters/robotwin20/runtime/locateanything_worker.py:L1-L242`, `sam2_worker.py:L1-L186`, and `worker_protocol.py:L1-L60` are adapter-owned entrypoints for the two existing isolated model environments.
- `examples/forge-adapters/robotwin20/profiles/robotwin20/perception.yaml:L1-L56` externalizes interpreters, model revision, checkpoint, CUDA device, caches, artifact roots, and timeouts.
- Adapter/workflow tests cover worker protocol failures, request binding, proposal ambiguity, mask/depth/calibration validation, artifact traversal and rollback, and the no-motion Gateway route.

### Validation

- PAOS/workflow/adapter suite: `281 passed, 2 skipped`; model-side tests skip because PAOS intentionally has no NumPy/Pillow.
- Isolated adapter numerical/worker suite: `27 passed`.
- Real no-motion composition on an existing RoboTwin RGB-D capture returned one LocateAnything proposal, an aligned SAM2 mask, 788 camera-frame points, all three derived artifacts, and `motion_authorized=false`; both worker processes exited.
- Ruff, compileall, and `git diff --check` passed. A system-Python whole-suite attempt was not accepted because that interpreter lacks PAOS `loguru` and asyncio test dependencies.
- `.codegraph/` and `.cursor/` remain untracked and are not staged.

## [v2.8.15] - 2026-09-03

Extended the provider-neutral `scene.understand` Query with auditable derived
perception artifacts for instance masks, object point clouds, and metric
localization. Every artifact is bound to the observation, scene revision,
entity, frame, calibration, source lineage, and root provenance; no Action or
motion authorization was added. The independent RoboTwin adapter forwards only
plain mappings and remains free of PAOS, simulator, Torch, and model imports.

扩展 provider-neutral `scene.understand` Query，增加可审计的实例 mask、目标点云和度量定位
派生资产。每个资产绑定 observation、scene revision、entity、frame、calibration、source
lineage 和 root provenance；没有增加 Action 或运动授权。独立 RoboTwin adapter 只转发普通
mapping，仍不依赖 PAOS、仿真器、Torch 或模型导入。

### Validation

- `268 passed` for the workflow and RoboTwin adapter suites.
- Ruff, compileall, ToolSpec YAML equality, and `git diff --check` passed.
- `.codegraph/` and `.cursor/` remain untracked and were not staged.

## [v2.8.14] - 2026-09-03

整理两条 provider-neutral 感知接入方案：单视角
`LocateAnything → SAM2 → RGB-D localization`，以及多视角
`MultiViewObservationSet → cross-view segmentation/identity/geometry fusion`。
明确多视角不是 RoboTwin Skill 或模型 Tool；融合实体几何可供
`scene.understand` / `grasp.propose`，Global SceneGeometry 仅作为独立可选输出，
所有结果仍须经过 PAOS provenance、frame/calibration 和 fail-closed 门禁。

Consolidated two provider-neutral perception paths: single-view
`LocateAnything → SAM2 → RGB-D localization`, and multi-view
`MultiViewObservationSet → cross-view segmentation/identity/geometry fusion`.
Clarified that multi-view is neither a RoboTwin Skill nor a model Tool; fused
entity geometry may feed `scene.understand` / `grasp.propose`, while Global
SceneGeometry remains a separate optional output under PAOS provenance,
frame/calibration, and fail-closed gates.

### Validation

- `git diff --check` passed.
- Execution document audit confirms no direct Agent-to-model/Dora/SDK path and no implicit camera motion.
- `.codegraph/` and `.cursor/` remain untracked and were not staged.

## [v2.8.13] - 2026-09-03

Fixed the GPT Responses strict JSON schema by declaring `spatial_envelopes.unit`
as a typed string const. Added recursive regression checks because the fake
Responses client does not validate request schemas. Updated the RoboTwin
adapter diagnosis and README to keep recognition, segmentation, metric
localization, grasp-pose proposal, readiness, and execution in their PAOS
use-case boundaries; the current GPT provider remains RGB semantic-only.

修正 GPT Responses strict JSON schema，为 `spatial_envelopes.unit` 补充
`type: string`，并增加递归回归校验，避免 Fake client 遗漏真实 API 的请求阶段错误。
同步更新 RoboTwin adapter 诊断与 README，明确识别、分割、度量定位、抓取位姿、准入和执行的
PAOS 用例归属；当前 GPT provider 仍只负责 RGB 语义理解。

### Validation

- `261 passed` for the adapter/workflow suites.
- Ruff, compileall, and `git diff --check` passed.
- `.codegraph/` and `.cursor/` remain untracked and were not staged.

## [v2.8.12] - 2026-09-03

Added an adapter-side `FilesystemArtifactResolver` for external RoboTwin
observation artifacts. It safely maps opaque RGB artifact references to files
under an explicitly external absolute root, rejects traversal/non-image refs,
and enables the GPT scene-understanding provider to consume real runtime
captures without exposing paths or assets to PAOS.

为外部 RoboTwin observation artifact 增加 adapter 侧 `FilesystemArtifactResolver`。它只在显式外部绝对根目录
下安全解析 opaque RGB artifact 引用，拒绝路径穿越和非图像 refs，使 GPT 场景理解 provider 能消费真实 runtime
capture，同时不向 PAOS 暴露本地路径或资产。

### Validation

- `260 passed in 2.62s` for the adapter/workflow suites.
- Ruff, compileall, and `git diff --check` passed.
- Complete `ForgeToolClient -> Fake Gateway -> generic endpoint -> RoboTwin provider -> GPT client` route is covered by a fake Responses client test.
- No live API call was attempted because `HEPHAESTUS_RELAY_API_KEY` remains absent; no real model result is claimed.
- `.codegraph/` and `.cursor/` remain untracked and were not staged.

## [v2.8.10] - 2026-09-02

Removed the duplicate provider-neutral `RoboTwinUnderstandingSnapshot` from
the adapter. The compatibility name now aliases PAOS's
`UnderstandingSnapshot`, so the adapter only translates inference inputs and
outputs while PAOS remains the sole owner of the public scene-understanding
snapshot contract.

移除 adapter 中重复的 provider-neutral `RoboTwinUnderstandingSnapshot`。兼容名称现在指向 PAOS 的
`UnderstandingSnapshot`，adapter 只负责 inference 输入/输出转换，PAOS 继续作为 scene-understand snapshot
公共契约的唯一所有者。

### Validation

- `251 passed` for the adapter/workflow suites.
- Ruff, compileall, and `git diff --check` passed.
- Provider-specific output remains fail-closed and the ForgeToolClient/Fake Gateway path is unchanged.

## [v2.8.9] - 2026-09-02

Moved the provider-neutral `manipulation.prepare` Query implementation into
the PAOS-owned generic capability runtime. The runtime owns candidate binding,
preparation identity, workspace/kinematic/collision check validation, evidence
projection, stale/empty/unavailable/invalid states, and the fixed
`motion_authorized: false` boundary. The Skill module is now a compatibility
export only; no robot, simulator, or model dependency was added.

将 provider-neutral `manipulation.prepare` Query 实现迁移到 PAOS 自有 generic capability runtime。运行时统一
持有候选绑定、preparation identity、workspace/kinematic/collision 检查校验、证据投影、
stale/empty/unavailable/invalid 状态以及固定的 `motion_authorized: false` 边界。Skill 模块仅保留兼容导出，
未加入机器人、仿真器或模型依赖。

### Validation

- `250 passed` for the adapter/workflow suites.
- Ruff, compileall, and `git diff --check` passed.
- `manipulation.prepare` remains read-only; no Action/Session/motion route is created.

## [v2.8.8] - 2026-09-02

Moved the provider-neutral `grasp.propose` Query implementation into the
PAOS-owned generic capability runtime. The runtime now owns the strict
ToolSpec, observation/frame/calibration binding, candidate and candidate-set
identity, funnel reconciliation, provenance validation, stale/empty/
unavailable/invalid states, and fail-closed provider error projection. The
Skill module is now a compatibility export only, and preparation imports the
shared candidate validator directly from PAOS. No YOLO, GraspGen, RoboTwin,
SAPIEN, Torch, Dora, or Hephaestus dependency was added.

将 provider-neutral `grasp.propose` Query 实现迁移到 PAOS 自有 generic capability runtime。运行时统一持有
严格 ToolSpec、observation/frame/calibration 绑定、候选与候选集身份、funnel 对账、provenance 校验、
stale/empty/unavailable/invalid 状态以及 provider 异常的 fail-closed 投影；Skill 模块仅保留兼容导出，
准备能力直接导入 PAOS 的候选校验器。未加入 YOLO、GraspGen、RoboTwin、SAPIEN、Torch、Dora 或 Hephaestus
依赖。

### Validation

- `249 passed` for the adapter/workflow suites.
- Ruff, compileall, and `git diff --check` passed.
- `grasp.propose` remains Query-only; no Action/Session/motion route is created.

## [v2.8.7] - 2026-09-02

Moved the provider-neutral `scene.understand` contract into the PAOS-owned
generic capability runtime. ToolSpec validation, observation/artifact binding,
scene-graph snapshot validation, stale rejection, provider error projection,
and Query result projection now live under
`PhyAgentOS.forge.capability_runtime.understanding`. The Skill module is only a
compatibility export; no Hephaestus, RoboTwin, SAPIEN, Torch, YOLO, Dora, or
motion dependency was added.

将 provider-neutral `scene.understand` 契约迁移到 PAOS 自有的 generic capability runtime。ToolSpec 校验、
observation/artifact 绑定、场景图 snapshot 校验、stale 拒绝、provider 错误投影和 Query 结果投影均由
`PhyAgentOS.forge.capability_runtime.understanding` 持有；Skill 模块仅保留兼容导出。未加入 Hephaestus、
RoboTwin、SAPIEN、Torch、YOLO、Dora 或运动依赖。

### Validation

- `248 passed in 2.64s` for adapter/workflow tests.
- Ruff, compileall, and `git diff --check` passed.
- Existing Skill imports remain compatible while resolving to the PAOS-owned implementation.

## [v2.8.6] - 2026-09-02

Added the independent RoboTwin adapter seam for the existing provider-neutral
`scene.understand` Query. `RoboTwinSceneUnderstandingProvider` accepts an
injected inference service, forwards only `scene.observe` identity/artifact
references, and rejects provider-specific fields. The generic endpoint now
projects provider failures as explicit `understanding_provider_error` results.
No detector/VLM/YOLO or simulator truth is included.

按 v1.0 扩展原则，在现有 provider-neutral `scene.understand` Query 后增加独立 RoboTwin adapter seam。
`RoboTwinSceneUnderstandingProvider` 只转发 `scene.observe` 身份与 artifact 引用，拒绝 provider 专有字段；
通用 endpoint 将 provider 异常投影为明确的 `understanding_provider_error` 结果。不包含检测器、VLM、YOLO
或仿真真值。

### Validation

- `248 passed in 2.65s` for adapter/workflow tests.
- Ruff, compileall, and `git diff --check` passed.
- No Action/Session/motion route or simulator/model import was added.

## [v2.8.5] - 2026-09-02

Unified Fake Gateway and RoboTwin `scene.observe` results behind the existing
`ForgeToolClient.invoke_query_tool` path. Added a runtime-only
`RoboTwinObservationProvider` that projects camera/depth/state captures into
provider-neutral observation identity, frame, calibration, freshness, and typed
artifact references. The adapter accepts either the external runtime capture
seam or the injected `RoboTwin20Adapter` seam; PAOS remains free of RoboTwin,
SAPIEN, Torch, and model imports. Relaxed the Fake Gateway artifact-reference
validator to accept capture subpaths, and added equality/integration tests.

通过既有 `ForgeToolClient.invoke_query_tool` 路径统一 Fake Gateway 与 RoboTwin 的 `scene.observe` 结果。
新增 runtime-only `RoboTwinObservationProvider`，将 camera/depth/state capture 投影为 provider-neutral 的
observation identity、frame、calibration、freshness 与 typed artifact refs；支持外部 runtime capture seam
和注入式 `RoboTwin20Adapter` seam。PAOS 仍不包含 RoboTwin、SAPIEN、Torch 或模型导入；Fake Gateway
artifact ref 校验支持 capture 子路径，并新增一致性集成测试。

### Validation

- `244 passed in 2.53s` for adapter/workflow tests.
- Ruff, compileall, and `git diff --check` passed.
- External RoboTwin20 `--format scene_observe` smoke returned the expected observation reference and RGB/depth/state artifacts; OIDN CUDA warnings remain a known runtime risk.
- `.codegraph/` and `.cursor/` remain untracked and were not staged.

## [v2.8.4] - 2026-09-02

Fixed the external RoboTwin runtime working-directory boundary in
`examples/forge-adapters/robotwin20/runtime/robotwin_backend.py:L88-L101,L119-L120,L179-L184,L208-L209,L223-L224`.
Official imports, `setup_demo`, `get_obs`, and `close_env` now run under the
runtime checkout and restore the caller's cwd. This removes the real smoke
failure caused by RoboTwin's relative `assets/objects/objaverse/list.json`
lookup when launched from the PAOS root. Added the regression test at
`tests/test_robotwin_backend_contract.py:L55-L65`.

修复独立 RoboTwin runtime 的工作目录边界：官方导入、场景初始化、观测读取和关闭均在外部 runtime checkout
上下文中执行并恢复调用方 cwd，消除从 PAOS 根目录启动时的相对资产路径错误。新增 cwd 回归测试；不改变
PAOS 依赖、ToolSpec 或动作权限。

## [v2.8.3] - 2026-09-02

Added the runtime-only `RoboTwinSensorBackend` at
`examples/forge-adapters/robotwin20/runtime/robotwin_backend.py:L1-L338` and
 contract tests at `tests/test_robotwin_backend_contract.py:L1-L77`. The backend
uses the official task's rendered RGB/depth and joint/end-effector state,
persists calibration and typed external artifacts, and injects through the
provider-neutral `RoboTwin20Adapter`. It rejects simulator truth channels and
never calls action/evaluator APIs. A real `beat_block_hammer/demo_clean` seed-0
capture produced 240x320 RGB/depth artifacts; SAPIEN OIDN CUDA warnings remain a
known runtime risk.

新增 runtime-only `RoboTwinSensorBackend`，通过 provider-neutral `RoboTwin20Adapter` 暴露真实 RGB/depth/state
artifact 与 calibration；不导出 actor/segmentation truth，不调用动作或 evaluator。真实 seed-0 capture 已验证，
但 OIDN CUDA warning 仍是运行时风险。

## [v2.8.2] - 2026-09-02

Added the standard-library fail-closed preflight at
`examples/forge-adapters/robotwin20/src/robotwin20_adapter/preflight.py:L1-L284`,
its tests at `tests/test_preflight.py:L1-L75`, and the `robotwin20-preflight`
entry point in `pyproject.toml:L1-L13`. The user-provided external RoboTwin20
environment passed all 16 checks (`ready=true`), including assets, CUDA
`sm_120`, SAPIEN, Vulkan, and task import, without modifying PAOS dependencies.

新增只使用标准库的 fail-closed preflight 与测试及 console entry point。用户提供的隔离 RoboTwin20 环境 16 项
检查全部通过（`ready=true`），包含官方 assets、CUDA `sm_120`、SAPIEN、Vulkan 与 task import；PAOS 依赖未被污染。

## [v2.8.1] - 2026-09-02

Verified the isolated `RoboTwin20` conda environment and checked out the official RoboTwin 2.0 source with
its pinned `XPolicyLab` submodule under `/home/yanxu/robotwin20-runtime/RoboTwin`. Confirmed the official asset
source is the Hugging Face dataset `TianxingChen/RoboTwin2.0`; only `embodiments.zip` was downloaded and verified.
The large `background_texture.zip` and `objects.zip` archives remain for the user to download. No PAOS dependency,
wheel content, ToolSpec, Hephaestus source, or tracked simulator asset was changed.

已核对隔离 `RoboTwin20` conda 环境，并将官方 RoboTwin 2.0 源码及固定的 `XPolicyLab` 子模块 checkout 到
`/home/yanxu/robotwin20-runtime/RoboTwin`。确认官方资产来源为 Hugging Face 数据集
`TianxingChen/RoboTwin2.0`；本次仅下载并校验 `embodiments.zip`，大型 `background_texture.zip` 与
`objects.zip` 留待用户自行下载。未修改 PAOS 依赖、wheel 内容、ToolSpec、Hephaestus 源码或已跟踪仿真资产。

### Validation

- `RoboTwin20` Python `3.10.21`; SAPIEN/Torch/TorchVision/OpenCV/Gymnasium/Open3D present.
- `embodiments.zip`: `219859313` bytes, SHA-256 `6b87d7d55e106d8ff25917e0538eb1e177fc549280e8a742a8cec3cb9f953fc6`.
- Official sizes: `background_texture.zip` `10970687027` bytes; `objects.zip` `3737778549` bytes.
- `.codegraph/` and `.cursor/` remain untracked and were not staged.

## [v2.8.0] - 2026-09-02

Implemented the first RoboTwin 2.0 adapter slice: an environment-owned lifecycle seam and sensor-only observation
source that can be connected to camera/depth/state outputs without importing RoboTwin into PAOS.

### Changed

- Added an independently packaged `robotwin20` adapter with explicit backend and sensor artifact protocols.
- Requires RGB/depth/state artifacts, frame, calibration, timestamp, and scene revision; rejects missing or
  simulator-ground-truth-only observations.
- Added no-motion tests; no YOLO, SAPIEN, robot SDK, Dora, or actuator dependencies were added to PAOS.

## [v2.7.0] - 2026-09-02

Implemented the simulator-free generic capability runtime foundation for the next integration phase.

### Changed

- Added reusable ToolEndpoint registration, discovery/context, Query dispatch, and bounded Action lifecycle
  primitives under `PhyAgentOS.forge`, with provider ports defined independently of RoboTwin, SAPIEN, YOLO,
  robot SDKs, and hardware.
- Added no-motion conformance tests and documented that this phase does not implement perception models or
  physical execution.

## [v2.6.3] - 2026-09-02

Corrected the documented extension order so the independent generic capability runtime is implemented before
any RoboTwin adapter work.

### Changed

- Added the simulator-free generic ToolEndpoint/provider-port phase to the bilingual user development guides.
- RoboTwin remains a profile-selected EnvironmentAdapter and simulation ground truth remains comparison-only.

## [v2.6.2] - 2026-09-02

Renamed the six-Tool workflow Skill to `pick-place-workflow` and corrected the RoboTwin perception boundary.

### Changed

- The Skill name now describes the complete observe → understand → propose → prepare → acquire → place workflow;
  the six stable Tool IDs are unchanged.
- PAOS v1.0 still requires an independent generic capability runtime. RoboTwin actor/entity truth, segmentation,
  object metadata, internal poses, and `check_success()` are simulation comparison/acceptance facts only; real
  deployment must use sensor artifacts and replaceable perception providers.
- Renamed `examples/forge-skills/scene-observe/` to `examples/forge-skills/pick-place-workflow/` and synchronized
  package imports, tests, manifest, and runtime discovery fixtures.

### Validation

- `220 passed`; `ruff check`; `compileall`; and `git diff --check` passed.
- No Dora, real Gateway server, RoboTwin, hardware, or motion route was started.

## [v2.6.1] - 2026-09-02

Saved and reviewed the RoboTwin adapter refactor diagnosis, separating reusable capability runtime semantics
from environment-specific adapters.

### Added

- Added `docs/forge/ROBOTWIN_ADAPTER_REFACTOR_DIAGNOSIS.md` with ownership boundaries, six-Tool migration seams,
  clean-room reimplementation rules, profile strategy, and acceptance gates.

### Changed

- Added diagnosis links to the Forge contract and documentation index.

### Security

- Documentation-only change; no Hephaestus, PAOS runtime, Gateway implementation, simulator, hardware, or motion path changed.

## [v2.6.0] - 2026-09-02

Clarified the v1.0 PAOS boundary for simulator integration and corrected the RoboTwin execution order.

### Changed

- Skills expose provider-neutral ToolSpecs and workflow guidance; RoboTwin 2.0 remains an independent
  Gateway/ToolEndpoint/Dora/simulator runtime.
- Documented that RoboTwin task, SAPIEN, embodiment, and benchmark configuration belongs in the adapter/profile,
  while a Skill Bundle freezes only runtime wiring and locked artifacts.

### Security

- Documentation-only change; no PAOS runtime, Gateway implementation, simulator, hardware, or motion path changed.

## [v2.5.3] - 2026-09-02

Added a reusable v1.0 feature-reference-card method for planning and reviewing PAOS extensions.

### Added

- Added `docs/forge/FEATURE_REFERENCE_CARDS.md`, linking normative documentation, selected extension points, ownership, failure semantics, implementation modules, tests, and PR traceability.

### Security

- Documentation-only change; no Gateway, Runtime, simulator, hardware, or motion path changed.

## [v2.5.1] - 2026-09-02

Backfilled the v2.5.0 verification-context commit and root index record.

### Changed

- Recorded commit `d6f6a74` and synchronized the bilingual monthly log with the root index.

### Security

- Documentation-only change; no runtime, Gateway, simulator, hardware, or motion path changed.

## [v2.5.0] - 2026-09-02

Added bound AgentTask verification-context integration coverage.

### Added

- Added an integration test that routes bound Query and bounded Action execution facts through
  `VerificationRequestBuilder` into the generic verifier context.
- Verified frozen binding/revision/invocation identity, execution-fact-only capability projections,
  opaque capability artifact references, and the absence of motion authorization in verifier input.

### Security

- The test uses only the Fake Gateway no-motion path and starts no Dora, simulator, hardware, or
  motion route.

## [v2.4.0] - 2026-09-02

Added ExperienceCoordinator recovery-episode integration coverage.

### Added

- Added tests confirming one recovered AgentTask becomes one processed TaskEpisode with preserved
  `replan_required → success` lineage delivered to the analyzer.
- Added assertions that capability facts alone do not create Skill candidates or Lesson clusters.

### Security

- Recovery episode tests execute no real Action, Session, Dora, hardware, or motion route.

## [v2.3.0] - 2026-09-02

Added generic AgentTask verification and recovery coverage.

### Added

- Added deterministic verifier tests for `replan_required`, append-only PlanRevision recovery, and
  final success on the same AgentTask.
- Verified recovered TaskEpisode lineage preserves both the replan-required and successful
  revisions.

### Security

- Recovery tests execute only Fake Gateway Queries and do not create motion, Session, or Dora
  execution.

## [v2.2.0] - 2026-09-02

Added governed execution record coverage after immutable Skill binding.

### Added

- Added a bound Query and bounded Action integration test through `AgentTaskCoordinator` and the
  standard Forge Tool API.
- Verified binding ID, revision ID, ToolSpec digest, invocation/attempt references, and capability
  outcome summary on persisted records.

### Security

- Execution remains on the Fake Gateway no-motion path; no real robot or simulator is invoked.

## [v2.1.0] - 2026-09-02

Added activation-to-AgentTask immutable binding integration coverage for the scene-observe Skill.

### Added

- Added tests connecting `SkillActivationManager`, `ForgeSkillBindingResolver`, and
  `AgentTaskCoordinator` through one primary Skill activation and frozen binding.
- Added fail-closed coverage for Runtime identity drift before governed Query access.

### Security

- The integration performs no Action, Session, Dora, hardware, or motion execution.

## [v2.0.0] - 2026-09-02

Added immutable Forge Skill binding coverage for the provider-neutral scene-observe Bundle.

### Added

- Added preview/freeze tests for manifest, SKILL document, Runtime identity, and all required
  ToolSpec hashes.
- Added fail-closed validation tests for Runtime replacement and ToolSpec tampering after binding.

### Security

- Binding tests execute no Action or Session and do not start Dora, hardware, or motion routes.

## [v1.9.0] - 2026-09-02

Added Runtime controller switch and rollback protection coverage.

### Added

- Added tests that block Skill Runtime switching while an AgentTask is non-terminal.
- Added rollback coverage for failed target startup and atomic active-registry replacement after a
  healthy target check.

### Security

- Tests use fake catalog/manager state only and start no Dora, Gateway, simulator, hardware, or
  motion route.

## [v1.8.0] - 2026-09-02

Added HTTP health-contract coverage for the RuntimeManager's Gateway and required Tool context
checks.

### Added

- Added a localhost-only HTTP fixture exercising real `RuntimeManager.status()` `/tools` and
  required `/context` reads.
- Added fail-closed verification that a missing or unavailable Tool context persists Runtime state
  as `failed` and prevents active-runtime publication.

### Security

- The test starts no Dora flow, hardware process, simulator, or motion route.

## [v1.7.0] - 2026-09-02

Added manifest-v2 Bundle installation and healthy Runtime discovery coverage for the
provider-neutral scene-observe Skill.

### Added

- Added isolated archive install/reload tests through `SkillInstaller` and `SkillCatalog`.
- Added fail-closed discovery tests for a single running runtime with all Tool contexts ready and
  for non-ready runtime states.

### Changed

- Marked the no-binary fake profile as `artifacts.resolver: local`; registry resolution remains
  reserved for Bundles with explicit Node locks.

## [v1.6.0] - 2026-09-02

Added a full no-motion AgentTask workflow integration fixture for the provider-neutral
scene-observe Bundle.

### Added

- Added an end-to-end test using `AgentTaskCoordinator -> ForgeToolClient -> FakeGatewayTransport`
  across observe, understand, propose, prepare, acquire, and place.
- Verified one task/revision, terminal Query/Action records, capability outcome projection, and
  synchronous `ExperienceCoordinator` `TaskEpisode` persistence.
- Covered non-terminal finalization rejection, unknown-action resend blocking, and cancellation
  reconciliation without introducing a second execution protocol or RoboTwin dependency.

## [v1.5.0] - 2026-09-02

Skill candidate support is now partitioned by bounded capability failure-owner scope. Successful
episodes with different scopes create independent candidates and cannot share promotion counts.

### Changed

- Added `capability_failure_owners` to `SkillCandidate`.
- Included owner scope in candidate identity and support matching while preserving legacy empty-scope
  compatibility and existing promotion thresholds.

## [v1.4.0] - 2026-09-02

Active Lesson counterexamples now require an exact capability failure-owner scope match. Mismatched
or scoped/legacy-missing scopes are recorded diagnostically and cannot retire or weaken a Lesson.

### Changed

- Added bounded owner-scope persistence to `ScopedLesson` and exact-scope counterexample checks.
- Preserved legacy behavior when both Lesson and episode have empty owner scopes.

## [v1.3.0] - 2026-09-02

Lesson activation now validates cross-episode capability failure-owner scope. Same-owner
observations may aggregate, while different-owner or scoped/legacy mixtures remain blocked before
synthesis and activation.

### Changed

- Added bounded owner-scope validation to LessonCluster synthesis and direct activation paths.
- Added idempotent `lesson_cluster_attribution_blocked` diagnostics without changing task verdicts,
  Tool API behavior, or Skill promotion thresholds.

## [v1.2.0] - 2026-09-02

Lesson clusters now retain a bounded capability failure-owner scope. Cross-episode observations
with different explicit root-cause owners cannot merge into one reusable Lesson pattern.

### Changed

- Added owner-scope persistence to `FailureObservation` and `LessonCluster`.
- Cluster matching rejects mismatched non-empty capability owner scopes while preserving the
  existing Skill/workflow scope and unique root-task support rules.

## [v0.9.0] - 2026-09-02

Capability outcome facts now flow from verified AgentTask execution records into the experience
and Skill-evolution input without changing task verdict authority or Forge execution boundaries.

### Added

- Added versioned `CapabilityOutcomeFact` and bounded `CapabilityOutcomeErrorFact` records to
  `TaskOutcomeEnvelope`.
- Added AgentTask outcome-source projection with provider-private Tool ID filtering and tests for
  redaction, unknown/failed states, malformed summaries, and diagnostic errors.

### Changed

- Experience analysis now receives only provider-neutral phase/status/owner/world-change/evidence
  facts. Artifact URIs and failure codes remain excluded, and facts/errors cannot authorize
  verdicts, learnability, or Skill/Lesson promotion.

## [v0.8.0] - 2026-09-02

Added a generic verification-layer projection for versioned Forge capability outcomes. The
projection exposes execution facts to AgentTask verification without creating a second execution
protocol or authorizing task success.

### Added

- Added `PhyAgentOS.verification.outcome_projection` for terminal Action summaries, including
  bounded validation of status, capability phase, failure ownership, evidence availability,
  opaque artifact references, metric names, and post-release evidence.
- Added AgentTask verifier-context fields for capability outcome projections and bounded projection
  errors while preserving the existing evidence allowlist and verdict flow.
- Added 14 projection tests covering valid outcomes, malformed summaries, unknown/failure paths,
  post-release evidence, missing summaries, and request-builder integration.

### Changed

- Documented the `execution_fact_only` authority boundary and fixed
  `task_success_authorized=false`; only `TaskVerificationContract` and the generic verifier may
  produce a user-level task verdict.

### Security

- Gateway artifact references remain opaque and are never promoted into `valid_evidence_refs`.
- Projection performs no Gateway calls, motion admission, retry, or PlanRevision mutation.

## [v1.0.0] - 2026-08-30

Initial stable release of PhyAgentOS.

### Security

- Upgraded `@whiskeysockets/baileys` to `7.0.0-rc14` to address
  `CVE-2026-48063` / `GHSA-qvv5-jq5g-4cgg`, and locked the Bridge dependency graph.

## [v0.2.3] - 2026-08-27

PhyAgentOS can run independently distributed Forge Skills through a task-scoped, immutable
Skill/Runtime/ToolSpec binding while keeping Gateway as the execution authority.

### Added

- Added first-class Query, Action, and Session Tool API lifecycles, including Session ownership,
  status/result reconciliation, and owned stop behavior.
- Added activation-time binding previews and task-time frozen bindings containing exact Skill
  version, manifest and workflow hashes, Runtime/Gateway identity, ToolSpec hashes, and Node locks.
- Added crash recovery that reconciles persisted invocation IDs using reads only, plus
  version-scoped Forge experience and Lessons.
- Added deterministic Skill bundle packaging and exact single-executable Node archive locks.
- Added the optional Bundle startup hook
  `bash <bundle>/start.sh <skill-name> <skill-version>` and supplies `PAOS_SKILL_NAME` and
  `PAOS_SKILL_VERSION` to rendered dataflows and Dora process environments.

### Changed

- Forge Gateway selection now comes only from one explicitly started, healthy installed Skill
  Runtime; static `forge.enabled`, `forge.baseUrl`, and `forge.apiVersion` selectors are rejected.
- Runtime state uses schema v2 so Runtime/Gateway identities, Session references, task bindings,
  and force-stop audit records are mandatory and stable across restarts.
- Action admission persists a PAOS-generated caller ID and intent before the remote request.
  Timeouts and unknown results cannot trigger an automatic POST retry.
- Runtime stop and switching account for active invocations, Sessions, and task bindings; forced
  stop records an audit event.
- Resource Registry Skill lookup uses the name endpoint. `paos skill install --version` validates
  the downloaded manifest as a client-side constraint before Node resolution and installation
  commit; schema-v3 static indexes retain version selection.
- Runtime environment identity now covers the selected dataflow path and profile file digests, so
  configuration edits and dataflow-path changes rematerialize the environment.
- Expanded the bilingual integration guide with Bundle packaging, local validation, immutable
  Node/Bundle publication order, and Registry acceptance guidance.

### Fixed

- Forge Node downloads accept Registry responses that omit duplicate digest and size fields. The
  verified Skill lock remains the digest authority, while the direct-download endpoint supplies
  the content length before the archive is downloaded and checked.
- Documented the Dora CLI v0.4.1 and `dora-message` v0.7.0 Forge Skill compatibility baseline,
  version-pinned installation methods, PATH and lifecycle checks, and RuntimeManager's automatic
  local Dora service startup.
- Startup-hook failures, missing Bash, and execution errors now persist a `failed` lifecycle state
  and diagnostic log before Dora can start, rather than leaving stale or unstarted state.
- Start, stop, install/update commit, and removal now use a non-blocking cross-process lock per
  Skill, preventing overlapping lifecycle mutations while allowing automatic release on process
  exit.

### Removed

- Removed the concrete Forge Skill, simulation profile, and remote bundle-fetch helper from the
  PhyAgentOS distribution. Forge Skills and their nodes, models, and assets are installed
  independently when required.

### Security

- Skill and Node downloads require exact size and SHA-256 metadata, archive extraction remains
  bounded and link-safe, and mutations require task ownership plus live binding revalidation.
- Unknown remote effects retain Runtime safety guards until explicit operator resolution.

## [v0.2.2] - 2026-08-21

PhyAgentOS now uses one Forge Query/Action Tool API execution plane while retaining Agent verification, experience, evolution, and the existing general-purpose tool platform.

### Added

- Added the AgentTask lifecycle tools `forge_task_create`, `forge_task_get`, `forge_task_begin_revision`, `forge_task_finalize`, and `forge_task_cancel` with one global non-terminal task, immutable PlanRevisions, bound Query records, Action invocation references, evidence, and aggregate verification.
- Added the Forge Tool API tools `forge_tool_context`, `forge_tool_query`, `forge_tool_start_action`, `forge_tool_action_status`, `forge_tool_action_result`, and `forge_tool_cancel_action` for bound and unbound Query/Action calls.
- Added the manifest-v2 Skill Runtime, catalog, archive validation, transactional installation, persistent runtime state, Resource Registry support, and `paos skill` / `paos forge-node` lifecycle commands.
- Added the built-in `move-arm-by-ee` v0.2 Skill with a MuJoCo profile, relative-pose Query, motion Action, gripper Action, ToolSpecs, and independently locked Forge nodes.
- Added backward-compatible AgentTask, PlanRevision, ToolInvocation, and attempt references to task experience and evolution records.

### Changed

- Robot execution now follows `AgentTask-bound or unbound call → ForgeToolClient → Gateway /tools → ToolInvocation → ToolEndpoint → Dora/robot`; operation `max_concurrency` remains the execution concurrency authority.
- Task verification now aggregates all calls bound to one AgentTask. A recovery verdict appends a bounded PlanRevision to the same task and continues through the existing verification and evolution policies.
- Skill discovery now combines workspace, installed, and built-in Skills. A healthy active Runtime contributes availability and its manifest `gateway_url` takes precedence over `forge.baseUrl`.
- `ForgeConfig` now represents `forge-tool-api.v1`; Resource Registry configuration is available through `resourceRegistry.url` or `PAOS_RESOURCE_REGISTRY_URL` and never triggers an implicit unconfigured download.
- Existing Agent tools, dynamic MCP tools, verification contracts, experience storage, evolution storage, and Skill activation remain available with their existing contracts.

### Removed

- Removed the PAOS Forge Session execution path and the seven Session-specific Agent tools: `forge_execute_task`, `forge_get_session`, `forge_cancel_session`, `forge_get_context`, `forge_reset`, `verify_forge_session`, and `create_replanned_forge_session`.
- Removed the built-in `pipergo2-demo`; `move-arm-by-ee` is the maintained robot Skill example.

### Fixed

- Cancellation acceptance, local timeout, and `unknown` invocation outcomes no longer imply that physical execution stopped and do not trigger blind retries.
- Skill and node installation now verifies SHA-256 metadata, blocks path traversal and unsafe links, validates locked node digests, and rolls back incomplete replacements.

### Security

- Runtime artifacts require verified size and digest metadata before installation; archive extraction is bounded and atomic, and no Registry download occurs without explicit configuration.

## [v0.2.1] - 2026-08-14

PhyAgentOS can turn verified Forge task outcomes into scoped, auditable workflow experience and supply activated Skill Lessons to verification as bounded, non-authoritative advice without changing the Forge execution path.

### Added

- Added explicit `activate_skill(name, role)` activation with one primary Skill, optional supporting Skills, applicable scoped Lessons, and task-to-Skill attribution.
- Added versioned task-outcome, episode, assessment, Skill candidate, failure observation, Lesson cluster, abstraction-validation, and scoped-Lesson contracts.
- Added a crash-safe SQLite WAL experience ledger, asynchronous reflection jobs, structured evolution events, Skill revision history, and generated per-Skill Lesson projections.
- Added guarded Skill creation/update after independent semantic-success support, including managed workflow blocks, workspace overrides for built-in Skills, reload validation, atomic writes, and rollback.
- Added workflow-related failure eligibility, normalized observation clustering, independent root-lineage support, Lesson synthesis, and abstraction validation.

### Changed

- Skill summaries now direct the Agent to activate a matching workflow before tool execution when evolution is enabled; direct `SKILL.md` reads are not treated as activation.
- Learned Lessons are loaded dynamically with the activated Skill. The root `LESSONS.md` remains available as legacy/human-authored material but is no longer injected globally while evolution is enabled.
- Forge verification uses the active scoped Lessons frozen with the root task's explicit Skill activations. Evolution mode never reads root `LESSONS.md` for automatic verification or review, and tasks without an activated Skill receive no learned Lesson context.
- Verifier prompts treat Lessons as untrusted, non-authoritative workflow advice that cannot establish criterion status, replace execution evidence, or appear as evidence references.
- Failures caused by unsatisfiable tasks, verifier/evidence limits, infrastructure, user constraints, or uncertain attribution remain diagnostic-only.
- Built-in Skills remain immutable; promoted revisions are written as workspace overrides and only the PAOS-managed workflow block is replaced on later updates.

### Security

- Experience records redact endpoint-, credential-, path-, executable-ID-, and action-assignment-shaped data and persist only workflow structure, input field names, opaque evidence references, and immutable record references.
- Lesson and Skill policies reject task-specific answers, fixed coordinates/values, credentials, endpoints, Gateway IDs, Action Manifest copies, prompt injection, and instructions that bypass Forge or verification.
