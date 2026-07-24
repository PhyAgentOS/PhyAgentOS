#!/usr/bin/env bash
# Start Isaac Sim TargetWS with GUI on this machine (native isaacsim3 + local DISPLAY).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

SCENE="${1:-pipergo2}"   # pipergo2 | merom
PORT="${2:-9003}"

if [[ ! -e asserts ]]; then
  OS3_ASSERTS="/home/zyserver/work/my_project/PhyAgentOS3/asserts"
  if [[ -d "$OS3_ASSERTS" ]]; then
    ln -sf "$OS3_ASSERTS" asserts
    echo "[start_isaacsim_gui] linked asserts -> $OS3_ASSERTS"
  else
    echo "[start_isaacsim_gui] ERROR: asserts/ missing. Link or copy scene USD first." >&2
    exit 1
  fi
fi

export DISPLAY="${DISPLAY:-:1}"
echo "[start_isaacsim_gui] DISPLAY=$DISPLAY"

case "$SCENE" in
  pipergo2)
    CONFIG="external/isaac_env/configs/pipergo2_manipulation_gui.json"
    ;;
  merom)
    CONFIG="external/isaac_env/configs/merom_multi_robot_gui.json"
    ;;
  *)
    echo "Usage: $0 [pipergo2|merom] [port]" >&2
    exit 1
    ;;
esac

echo "[start_isaacsim_gui] scene=$SCENE config=$CONFIG port=$PORT"
echo "[start_isaacsim_gui] First boot may take several minutes — wait for Isaac window + TargetWS listening."

exec python PhyAgentOS/runtime/targets/remote/isaacsim/server.py \
  --config "$CONFIG" --gui --port "$PORT"
