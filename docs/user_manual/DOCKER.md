# Docker 部署指南

> 版本：0.2.2 · [English](DOCKER_en.md)

PhyAgentOS 提供基于 Docker 的快速部署方案，无需手动配置 Python / Node.js 环境。配合 [`scripts/install.sh`](../../scripts/install.sh) 一键脚本，可在一分钟内完成构建、初始化与运行。

> 镜像基础：`ghcr.io/astral-sh/uv:python3.12-bookworm-slim`（CPU，约几百 MB）

---

## 📦 镜像包含什么

| 组件 | 说明 |
|:-----|:-----|
| Python 3.12 运行时 | 由 `uv` 安装 `pyproject.toml` 中的全部依赖 |
| `paos` CLI | 已注册为入口命令（`ENTRYPOINT`） |
| Node.js 20 | 用于编译 WhatsApp bridge（best-effort，见 [已知限制](#-已知限制)） |
| 配置目录 | `/root/.PhyAgentOS`（通过卷挂载到宿主机持久化） |
| 默认服务 | 交互式 CLI（`paos agent`），可切换为长驻网关 |

镜像**不包含** GPU / CUDA、Isaac Sim、BEHAVIOR-1K 等重依赖（位于 `external/`，需另外配置）。镜像定位是 Agent 与网关服务，连接外部的 Forge Gateway。

> **关于网关端口**：`paos gateway` 是消息总线服务（Agent + 频道 + Cron + Heartbeat + Forge 编排），**仅主动外连**（连接 LLM provider、Telegram/钉钉等频道），不监听入站端口。`config.json` 中的 `gateway.port` 当前仅用于启动日志展示，未绑定 socket，因此容器**无需** `-p` 端口映射。

---

## ✅ 前置条件

- **Docker 20.10+**（含 daemon 运行中）
- 可选：**Docker Compose v2**（若使用 `docker-compose.yml`）

检查环境：

```bash
docker --version
docker info   # 确认 daemon 正常运行
```

---

## 🚀 一键安装与运行

> 以下 `./scripts/install.sh` 命令均在**仓库根目录**执行。

最简流程，两条命令：

```bash
# 1. 构建镜像 + 写入默认配置（首次使用）
./scripts/install.sh

# 2. 编辑配置，填入 LLM API Key
#    macOS / Linux:  vi ~/.PhyAgentOS/config.json
#    在 providers.<name>.apiKey 处填入你的密钥

# 3. 进入交互式 CLI
./scripts/install.sh chat
```

### 完整命令列表

| 命令 | 作用 |
|:-----|:-----|
| `./scripts/install.sh` | （默认）构建镜像 + 初始化配置 |
| `./scripts/install.sh build` | 仅构建镜像 |
| `./scripts/install.sh onboard` | 仅写入默认配置到 `~/.PhyAgentOS/config.json` |
| `./scripts/install.sh chat` | 交互式 CLI（镜像默认服务） |
| `./scripts/install.sh gateway` | 启动长驻网关（消息总线，仅外连，无入站端口） |
| `./scripts/install.sh status` | 查看 PhyAgentOS 状态 |
| `./scripts/install.sh stop` | 停止网关容器 |
| `./scripts/install.sh logs` | 跟踪网关日志 |
| `./scripts/install.sh help` | 显示帮助 |

---

## ⚙️ 配置与环境变量

### 数据目录

所有配置、工作区、会话历史都保存在宿主机的 `~/.PhyAgentOS`，通过卷挂载（`-v`）注入容器：

```
宿主机 ~/.PhyAgentOS  ⟷  容器 /root/.PhyAgentOS
```

因此**卸载镜像不会丢失数据**，重新运行脚本即可恢复。

### 可配置环境变量

| 变量 | 默认值 | 说明 |
|:-----|:-------|:-----|
| `PAOS_DATA_DIR` | `~/.PhyAgentOS` | 配置与工作区目录 |

示例：自定义数据目录启动网关。

```bash
PAOS_DATA_DIR=/data/paos ./scripts/install.sh gateway
```

### API Key 配置

交互式 CLI 与网关都需要 LLM provider 的 API Key。安装脚本会在 `onboard` 阶段写入默认配置模板，编辑其中的 `providers` 段：

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "YOUR_API_KEY"
    }
  }
}
```

支持的 provider 及 OAuth 流程见 `paos provider login`。

---

## 🧩 使用 Docker Compose

仓库已提供 [`docker-compose.yml`](../../docker-compose.yml)，适合需要常驻服务的场景。

```bash
# 启动网关（后台常驻，自动重启）
docker compose up -d phyagentos-gateway

# 查看日志
docker compose logs -f phyagentos-gateway

# 进入交互式 CLI（独立 profile）
docker compose run --rm phyagentos-cli
```

---

## 🔧 直接使用 Docker（不用脚本）

如需完全手动控制（`docker build` 需在**仓库根目录**执行）：

```bash
# 构建
docker build -t phyagentos:latest .

# 初始化配置（首次）
docker run --rm -v ~/.PhyAgentOS:/root/.PhyAgentOS phyagentos:latest onboard

# 交互式 CLI
docker run --rm -it -v ~/.PhyAgentOS:/root/.PhyAgentOS phyagentos:latest agent

# 长驻网关（消息总线，仅外连，无需端口映射）
docker run -d --name phyagentos-gateway \
  -v ~/.PhyAgentOS:/root/.PhyAgentOS \
  phyagentos:latest gateway
```

---

## ⚠️ 已知限制

### 1. WhatsApp 渠道不可用

镜像构建 WhatsApp bridge 时采用 **best-effort** 策略：`@whiskeysockets/baileys` 的传递依赖 `libsignal-node` 通过 `git+ssh` 拉取，在隔离构建环境中会失败。因此：

- WhatsApp 渠道（`paos channels login`）**不可用**
- CLI、网关、其它渠道（Telegram / 钉钉 / 飞书等）**不受影响**

如需恢复 WhatsApp，需单独处理该依赖（锁定可走 HTTPS 的版本或镜像内配置 SSH 凭据）。

### 2. 容器以 root 运行

为保持与 `~/.PhyAgentOS:/root/.PhyAgentOS` 的卷挂载约定一致，镜像默认以 root 用户运行。如需生产硬化，建议后续添加非 root 用户与 healthcheck。

### 3. 不含 GPU 支持

本镜像为 CPU 版，不支持 Isaac Sim / BEHAVIOR-1K 等需要 CUDA 的仿真。如需 GPU，需改用 `nvidia/cuda` 基础镜像并以 `--gpus all` 运行。

---

## 🧯 排错

| 现象 | 解决方案 |
|:-----|:---------|
| `docker: command not found` | 安装 Docker：<https://docs.docker.com/get-docker> |
| `Cannot connect to the Docker daemon` | 启动 Docker Desktop 或 `sudo systemctl start docker` |
| 构建 OOM / 过慢 | 增大 Docker 内存分配；首次构建需下载依赖，后续走缓存 |
| `paos agent` 报 `No API key configured` | 编辑 `~/.PhyAgentOS/config.json` 填入 `apiKey` |
| 网关启动后立即退出 | 多为缺 API Key；`./scripts/install.sh logs` 查看日志确认 |
| 网关容器无法启动 | `docker rm -f phyagentos-gateway` 后重试 |

---

## 📚 相关文件

- [`Dockerfile`](../../Dockerfile) — 镜像构建定义
- [`docker-compose.yml`](../../docker-compose.yml) — Compose 编排
- [`.dockerignore`](../../.dockerignore) — 构建忽略规则
- [`scripts/install.sh`](../../scripts/install.sh) — 一键安装脚本
