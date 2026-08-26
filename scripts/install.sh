#!/usr/bin/env bash
#
# PhyAgentOS one-click installer (local build + run).
#
# Quick start:
#   ./scripts/install.sh           # build image + initialize config
#   ./scripts/install.sh chat      # interactive CLI (needs API key in config)
#   ./scripts/install.sh gateway   # long-running gateway service
#
set -euo pipefail

IMAGE="phyagentos:latest"
DATA_DIR="${PAOS_DATA_DIR:-$HOME/.PhyAgentOS}"
GATEWAY_NAME="phyagentos-gateway"

_ok()   { printf "\033[32m\u2713\033[0m %s\n" "$1"; }
_warn() { printf "\033[33m!\033[0m %s\n" "$1"; }
_err()  { printf "\033[31m\u2717\033[0m %s\n" "$1"; }
_info() { printf "\033[36m\u2192\033[0m %s\n" "$1"; }

require_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        _err "Docker not found. Install: https://docs.docker.com/get-docker"
        exit 1
    fi
    if ! docker info >/dev/null 2>&1; then
        _err "Docker daemon is not running. Start Docker Desktop or the docker service."
        exit 1
    fi
}

ensure_data() {
    mkdir -p "$DATA_DIR"
}

build() {
    require_docker
    _info "Building image $IMAGE ..."
    # Script lives in scripts/, build context is the repo root.
    local ctx
    ctx="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    docker build -t "$IMAGE" "$ctx"
    _ok "Image ready: $IMAGE"
}

onboard() {
    require_docker
    ensure_data
    _info "Initializing config under $DATA_DIR ..."
    docker run --rm -i \
        -v "$DATA_DIR:/root/.PhyAgentOS" \
        "$IMAGE" onboard
    _ok "Config initialized at $DATA_DIR/config.json"
    _warn "Now set providers.<name>.apiKey in that file, then run: $0 chat"
}

chat() {
    require_docker
    ensure_data
    docker run --rm -it \
        -v "$DATA_DIR:/root/.PhyAgentOS" \
        "$IMAGE" agent
}

gateway() {
    require_docker
    ensure_data
    _info "Starting gateway (message-bus service, outbound only) ..."
    docker rm -f "$GATEWAY_NAME" >/dev/null 2>&1 || true
    docker run -d --name "$GATEWAY_NAME" \
        --restart unless-stopped \
        -v "$DATA_DIR:/root/.PhyAgentOS" \
        "$IMAGE" gateway
    _ok "Gateway started. Tail logs: $0 logs"
}

status_cmd() {
    require_docker
    ensure_data
    docker run --rm \
        -v "$DATA_DIR:/root/.PhyAgentOS" \
        "$IMAGE" status
}

stop() {
    if docker rm -f "$GATEWAY_NAME" >/dev/null 2>&1; then
        _ok "Stopped $GATEWAY_NAME."
    else
        _warn "No gateway container running."
    fi
}

logs() {
    docker logs -f "$GATEWAY_NAME"
}

install_all() {
    build
    echo
    onboard
}

usage() {
    cat <<EOF
PhyAgentOS one-click installer (local build + run).

Usage: $0 <command>

Commands:
  (none) | install   Build image, then initialize config (one-click)
  build              Build the Docker image only
  onboard            Write default config to $DATA_DIR/config.json
  chat               Interactive CLI (default service)
  gateway            Long-running gateway (message bus, outbound only)
  status             Show PhyAgentOS status
  stop               Stop the gateway container
  logs               Tail gateway logs
  help               Show this help

Environment:
  PAOS_DATA_DIR      Config & workspace dir   (default: ~/.PhyAgentOS)
EOF
}

main() {
    case "${1:-install}" in
        install)        install_all ;;
        build)          build ;;
        onboard)        onboard ;;
        chat)           chat ;;
        gateway)        gateway ;;
        status)         status_cmd ;;
        stop)           stop ;;
        logs)           logs ;;
        help|-h|--help) usage ;;
        *) _err "Unknown command: $1"; echo; usage; exit 1 ;;
    esac
}

main "$@"
