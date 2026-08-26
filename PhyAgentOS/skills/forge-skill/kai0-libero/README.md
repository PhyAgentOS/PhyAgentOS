# kai0-libero

用 kai0（π0.5-libero checkpoint）在 LIBERO 仿真中运行评测批次。评测经 Gateway Action Tool
`kai0_libero.benchmark` 发起，`benchmark_action_policy`（Endpoint adapter）编排批次，批次内
`libero_benchmark` 与 `kai0_policy` 两节点协同推理，结果以 ToolResult 七字段返回。

本仓库为 **kai0-libero skill 的源码形态**。不含权重与二进制产物。

## 1. 仓库内容

```
kai0-libero/
├── SKILL.md                         # skill 说明
├── skill.yaml                       # skill 清单（4 个 Node 锁）
├── profiles/libero/
│   ├── dataflow.yaml                # 主 flow：gateway + benchmark_action_policy
│   ├── benchmark_action_policy.py   # adapter（Endpoint 协议 + 批次编排）
│   ├── gateway.yaml                 # Tool 声明与 provider 绑定
│   ├── adapter_config.yaml          # adapter 配置（部署时渲染 3 个占位符）
│   ├── bench_template.yaml          # benchmark 节点配置模板
│   ├── batch_dataflow.tpl.yaml      # 批次子 flow 模板（两节点）
│   └── kai0_libero.yaml             # 策略节点配置
├── scripts/
│   ├── setup_libero_env.sh          # 建 libero-bench conda 环境
│   ├── deploy_source.sh             # 源码形态一键部署
│   ├── download_pi05_libero.py      # 下载 π0.5-libero 权重
│   ├── check_server_readiness.sh    # 服务端就绪三查
│   ├── startup_selfcheck.py         # 环境口径自检
│   └── verify_result.py             # 结果文件校验
└── build/                           # 二进制重建配方（可选，见附录 A）
```

## 2. 组件与获取

| 部件 | 说明 | 获取渠道 |
|---|---|---|
| 本仓库 | skill 源码 | 本仓库 |
| kai0_policy 源码 | 含 LIBERO 契约（`inference/contract.py`） | gitlab `PhyAgentOS/framework/policies/embodied/kai0_runner`，main @ `60a1332` |
| openpi 服务端 | 推理服务（JAX/openpi，WebSocket :8000） | 同上的 `server/` 与 `scripts/start_server.sh` |
| libero_benchmark 源码 | benchmark 节点 | gitlab `PhyAgentOS/framework/benchmark/libero`，main @ `fac3db8` |
| LIBERO | 仿真任务与数据 | `github.com/Lifelong-Robot-Learning/LIBERO` @ `8f1084e3` |
| gateway 二进制 | demo 已发布件（无源码） | demo quick-start 离线包内 `bundles/nodes/gateway-0.2.0-linux-x86_64.tar.gz` |
| π0.5-libero 权重 | ~12.4GB | `python3 scripts/download_pi05_libero.py` |

## 3. 环境准备

要求：Linux x86_64，NVIDIA GPU ≥ 16GB 显存。

```bash
# 3.1 libero-bench conda 环境（benchmark 与 adapter 运行环境）
export LIBERO_REPO=<LIBERO 仓库根>
bash scripts/setup_libero_env.sh        # conda env libero-bench（py3.12.13），
                                        # 版本清单见附录 B；脚本末尾自带 import 自检

# 3.2 kai0_runner 客户端 venv（kai0_policy 运行环境）
cd <kai0_runner 仓库根>
uv sync --extra dev                     # 见 kai0_runner 仓 README

# 3.3 openpi 服务端 venv（JAX/CUDA）
cd <kai0_runner 仓库根>/server
bash setup.sh                           # 见 kai0_runner 仓 README

# 3.4 dora 与 paos CLI
conda create -n paos-skill-demo python=3.12 -y && conda activate paos-skill-demo
pip install dora-rs==0.4.1 dora-rs-cli==0.4.1 pyyaml
pip install phyagentos-ai==0.1.4.post4   # paos CLI（渠道见平台侧）
# 校验：dora --version；paos skill --help

# 3.5 权重
python3 scripts/download_pi05_libero.py  # 下载到 <本仓库>/weights/pi05_libero（幂等，可断点续跑）
```

## 4. 部署

```bash
bash scripts/deploy_source.sh \
  --kai0-runner <kai0_runner 仓库根> \
  --bench-node   <libero benchmark 仓库根> \
  --libero-repo  <LIBERO 仓库根> \
  --gateway-bundle <gateway-0.2.0-linux-x86_64.tar.gz>   # 本机未装 demo gateway 时必给
```

脚本执行五步：

1. 在 `~/.PhyAgentOS/forge_runtime/nodes/<node_id>/versions/<artifact_id>/` 下为三个节点
   放置可执行包装入口（内部 exec 解释器运行源码）并生成 `node-manifest.json`（digest 按
   运行时权威算法计算）；
2. 部署 gateway（复用本机已装的 demo 件，或从 `--gateway-bundle` 解包）；
3. 用新 digest 回填 `skill.yaml` 的三个节点锁（原文件备份为 `skill.yaml.bak`）；
4. 部署 skill 到 `~/.PhyAgentOS/skills/kai0-libero/`，并渲染 `adapter_config.yaml` 的
   `__RUN_ROOT__` / `__DORA_BIN__` / `__KAI0_CONFIG__` 占位符（只改部署副本）；
5. 写 `quick_start.env`（就绪检查脚本的配置）。

## 5. 启动与冒烟

```bash
# 5.1 启动 openpi 服务端（在 kai0_runner 仓库根）
nohup bash scripts/start_server.sh \
  --ckpt <本仓库>/weights/pi05_libero --policy-config pi05_libero \
  > /tmp/kai0-server.log 2>&1 &
until curl -s -m 5 http://127.0.0.1:8000/healthz | grep -q OK; do sleep 5; done

# 5.2 就绪三查（healthz / infer-once 7 维动作指纹 / norm_stats sha256）
bash scripts/check_server_readiness.sh   # 输出 READINESS_OK 才继续

# 5.3 启动 skill
paos skill start kai0-libero -p libero
paos skill status kai0-libero            # Gateway GET /tools: ready、Tool context ready

# 5.4 冒烟（小批次 2×2，跑完读回 benchmark_result）
paos agent -m "用 kai0_libero.benchmark 工具跑一个 libero_spatial 小批次冒烟：task_ids [0,1]、init_state_ids [0,1]、max_steps 220，跑完后读回 benchmark_result 并总结"
```

## 6. 收尾

```bash
paos skill stop kai0-libero
pkill -f serve_policy                    # 服务端必停，防过夜占 GPU
```

## 附录 A 重建二进制（可选）

改完源码需要出二进制分发时使用。`build/` 内的 spec 与脚本含开发机构建路径，按本机环境
改完后再执行：

```bash
# 构建环境：libero-bench env 与 kai0_runner venv 各装 PyInstaller 6.22.2
cd build
bash make_node_bundles.sh                # 产出 bundles/nodes/<artifact_id>.tar.gz
```

注意：

- 改源码后 node-manifest digest 会变，需重算并回填 `skill.yaml`（算法同
  `scripts/deploy_source.sh` 第 3 步）；
- `libero_benchmark` 单文件二进制约 809MB，超过安装器 512MB/文件的限制，生产形态需改
  PyInstaller onedir（launcher + `_internal/`）；
- 二进制形态的部署脚本（quick_start.sh）与离线包打包脚本不随本仓库分发，出二进制交付时
  向原作者索取。

## 附录 B 版本清单（libero-bench 环境，2026-08-20 冻结）

| 包 | 版本 | 备注 |
|---|---|---|
| python | 3.12.13 | conda `libero-bench` |
| dora-rs | 0.4.1 | 与 dora CLI 同版本 |
| forge-msgs | 1.0.0 | gitlab `PhyAgentOS/framework/forge.git` @ tag `forge-msgs-v1.0.0`，subdirectory `packages/msgs` |
| numpy | 1.26.4 | robosuite 解析会升 2.x，脚本内钉回 |
| robosuite / mujoco | 1.4.0 / 3.2.7 | |
| gym / bddl | 0.25.2 / 1.0.1 | bddl 需补 `future==0.18.2` |
| opencv-python | 4.10.0.84 | numpy 1.26.4 兼容 |
| torch | 2.5.1+cpu | 仅 init_states 的 torch.load |
| termcolor / h5py / pynput / easydict | 3.3.0 / 3.16.0 / 1.8.2 / 1.9 | robosuite/LIBERO 打包缺声明，需显式安装 |
| LIBERO | @ `8f1084e3` | **不 pip 安装**，运行与构建均用 `PYTHONPATH=<LIBERO 仓根>`；`~/.libero/config.yaml` 由 setup 脚本预写 |

其他环境：kai0_runner 客户端 venv（uv，`uv sync --extra dev`）、openpi 服务端 venv
（`server/setup.sh`，JAX/CUDA）、paos CLI 环境（`phyagentos-ai==0.1.4.post4` +
`dora-rs-cli==0.4.1`）。版本均以各自仓库 README 为准。
