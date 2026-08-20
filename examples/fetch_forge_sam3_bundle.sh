#!/usr/bin/env bash
# 下载 sam3_bundle demo 到与 PhyAgentOS 同级的 sam3_bundle。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHYAGENTOS_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_ROOT="$(cd "${PHYAGENTOS_ROOT}/.." && pwd)"

ENV_VERSION="${VERSION-}"
VERSION="${ENV_VERSION:-latest}"

_DEFAULT_SAM3_URL='https://meta-emt-dev.tos-cn-beijing.volces.com/tmp/sam3_grasp_runner.zip'
SAM3_URL="${SAM3_URL:-${_DEFAULT_SAM3_URL}}"
SAM3_BASE_URL="${SAM3_BASE_URL:-}"
SAM3_ARCHIVE="${SAM3_ARCHIVE:-sam3_bundle.zip}"
SAM3_TARGET_DIR="${SAM3_TARGET_DIR:-${WORKSPACE_ROOT}/sam3_bundle}"

usage() {
  cat <<EOF
用法: $(basename "$0") [--help]

下载并解压 sam3_bundle demo 到:
  ${SAM3_TARGET_DIR}

环境变量:
  VERSION=xxx          替换 URL 中的版本段（默认: latest）
  SAM3_URL=...         覆盖完整下载链接（默认使用 TOS 公共读链接；也兼容预签名 URL）
  SAM3_BASE_URL=...    覆盖下载目录前缀（设置后会拼接 SAM3_ARCHIVE；若需按版本换路径，字符串里应含字面量 \${VERSION}）
  SAM3_ARCHIVE=...     覆盖远端归档名（默认: sam3_bundle.zip）
  SAM3_TARGET_DIR=...  覆盖解压目标目录（默认: ${WORKSPACE_ROOT}/sam3_bundle）

更新时会清空 ${SAM3_TARGET_DIR} 后重新写入。
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

expand_version_in_url() {
  local raw="$1"
  local v="${VERSION:-latest}"
  echo "${raw//\$\{VERSION\}/${v}}"
}

download_one() {
  local url="$1"
  local out_path="$2"
  echo "==> wget: ${url}"
  wget -q --show-progress -O "${out_path}" "${url}" || {
    echo "ERROR: wget 失败: ${url}" >&2
    exit 1
  }
}

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

archive_path="${TMP_DIR}/${SAM3_ARCHIVE}"
if [[ -n "${SAM3_BASE_URL}" ]]; then
  url="$(expand_version_in_url "${SAM3_BASE_URL%/}/${SAM3_ARCHIVE}")"
else
  url="$(expand_version_in_url "${SAM3_URL}")"
fi
download_one "${url}" "${archive_path}"

echo "==> unzip: ${archive_path}"
unzip -qo "${archive_path}" -d "${TMP_DIR}/extract" || {
  echo "ERROR: unzip 失败: ${SAM3_ARCHIVE}" >&2
  exit 1
}

rm -rf "${SAM3_TARGET_DIR}"
mkdir -p "$(dirname "${SAM3_TARGET_DIR}")"

if [[ -d "${TMP_DIR}/extract/sam3_bundle" ]]; then
  mv "${TMP_DIR}/extract/sam3_bundle" "${SAM3_TARGET_DIR}"
else
  mkdir -p "${SAM3_TARGET_DIR}"
  shopt -s dotglob
  mv "${TMP_DIR}/extract"/* "${SAM3_TARGET_DIR}/"
  shopt -u dotglob
fi

find "${SAM3_TARGET_DIR}/scripts" -type f -name "*.sh" -exec chmod +x {} \; 2>/dev/null || true
echo "${VERSION:-latest}" > "${SAM3_TARGET_DIR}/.sam3_bundle_version"
date -u +%Y-%m-%dT%H:%M:%SZ > "${SAM3_TARGET_DIR}/.sam3_bundle_fetched_at" 2>/dev/null || true

echo "==> 完成。已更新目录: ${SAM3_TARGET_DIR}"
