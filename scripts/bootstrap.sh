#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[bootstrap] Blitz-Scale Edge Observer"
echo "[bootstrap] root: ${ROOT_DIR}"

missing=0

check_cmd() {
  local cmd="$1"
  local label="$2"
  if command -v "${cmd}" >/dev/null 2>&1; then
    echo "[ok] ${label}: $("${cmd}" --version 2>/dev/null | head -n1 || echo "installed")"
  else
    echo "[missing] ${label} (${cmd})"
    missing=1
  fi
}

check_cmd python3 "Python 3"
check_cmd node "Node.js"
check_cmd terraform "Terraform"
check_cmd aws "AWS CLI"
check_cmd wrangler "Cloudflare Wrangler"

echo "[bootstrap] Installing project dependencies"
if command -v python3 >/dev/null 2>&1; then
  python3 -m pip install -r "${ROOT_DIR}/requirements.txt" || true
fi

if command -v npm >/dev/null 2>&1; then
  (cd "${ROOT_DIR}/edge" && npm install)
fi

if [[ ${missing} -ne 0 ]]; then
  echo "[bootstrap] One or more required tools are missing."
  echo "[bootstrap] Install missing tools, then rerun scripts/bootstrap.sh"
  exit 1
fi

echo "[bootstrap] Completed successfully"
