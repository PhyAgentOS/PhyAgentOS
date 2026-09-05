# Franka `blocks_ranking_rgb` readiness 输入审计

日期：2026-09-04（Asia/Shanghai）  
范围：仅审计 readiness worker 的输入是否具备；不运行 Action、Gateway、Dora 或任何机器人运动。

## 结论

当前 readiness 状态为 `unavailable`。不能运行真实或独立 IK/碰撞 probe，也不能把现有 replay fixture 当作 Franka 的物理 readiness 证据。

原因是 Franka capture 与现有 GraspGen 结果不属于同一场景，且 Franka capture 尚无 geometry/candidate 产物：

| 检查项 | 结果 | 证据 |
|---|---|---|
| runtime profile | 通过 | `examples/forge-adapters/robotwin20/profiles/robotwin20/franka-blocks-ranking.yaml`，`blocks_ranking_rgb`、seed `0`、`[franka-panda, franka-panda, 0.8]` |
| no-motion scene capture | 通过 | `/home/yanxu/robotwin20-runtime/artifacts/paos-franka-blocks-ranking-v470-20260904T/blocks_ranking_rgb-0-1/blocks_ranking_rgb-0-1-000000/` |
| RGB/depth/state/calibration | 通过 | `rgb.png`、`depth.npy`、`state.json`、`calibration.json` |
| Franka geometry artifact | 缺失 | capture 目录没有 `derived/` 或 `point_cloud` 文件 |
| Franka grasp candidates | 缺失 | 没有与 `blocks_ranking_rgb-0-1` revision 绑定的 candidate set |
| GraspGen live result | 不可复用 | 现有结果绑定 `beat_block_hammer-0-1/head_camera`，不是 Franka scene |
| IK/collision/workspace evidence | 缺失 | 当前只有 replay worker conformance fixture |
| readiness probe | 未运行 | 输入完整性门禁拒绝启动 |

## 绑定核对

Franka capture 的场景 revision 为 `blocks_ranking_rgb-0-1`，frame 为 `head_camera`。现有 GraspGen 请求绑定：

```text
observation://beat_block_hammer-0-1/head_camera
candidate-set://beat_block_hammer-0-1/head_camera
```

二者 revision 不一致，因此不能将候选投影到 Franka 的 `manipulation.prepare` 请求。若强行复用，会绕过 observation、calibration 和 scene revision 的权威绑定。

## 已执行的安全边界

- 未调用 `play_once`、`check_success` 或任何 action route。
- 未启动 IK、碰撞规划、Action、Gateway、Dora 或硬件进程。
- 未生成 `prepared` candidate，也未创建 readiness replay artifact。
- 状态被明确记录为 `unavailable`，而不是“失败后伪造通过”。

## 下一步（按执行顺序）

1. 在同一 Franka capture 上完成 `scene.understand → geometry localization`，生成带 `observation_ref`、`scene_revision`、`frame_id`、`calibration_ref` 和实体引用的 point-cloud artifact。
2. 用该 geometry 运行真实 GraspGen，保存 candidate set、provider receipt 和完整 provenance。
3. 在 RoboTwin 外部 Python/planner 环境恢复后，运行独立 IK/collision/workspace readiness worker；worker 必须返回与 runtime profile 的 robot、gripper、topology、planner、profile digest 完全一致的 binding。
4. 保存不可变 readiness evidence，完成人工审核；审核前不得进入 Action/Gateway no-motion wiring。

