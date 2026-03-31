#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WRANGLER_FILE="${ROOT_DIR}/edge/wrangler.toml"

echo "[preflight] Blitz-Scale Edge Observer"

fail=0

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "[fail] Missing required command: ${cmd}"
    fail=1
  else
    echo "[ok] command available: ${cmd}"
  fi
}

require_cmd aws
require_cmd wrangler
require_cmd terraform
require_cmd python3
require_cmd node

if command -v aws >/dev/null 2>&1; then
  if aws sts get-caller-identity >/dev/null 2>&1; then
    echo "[ok] AWS auth configured"
  else
    echo "[fail] AWS auth missing (run: aws configure)"
    fail=1
  fi
fi

if command -v wrangler >/dev/null 2>&1; then
  if wrangler whoami >/dev/null 2>&1; then
    echo "[ok] Wrangler auth configured"
  else
    echo "[fail] Wrangler auth missing (run: wrangler login)"
    fail=1
  fi
fi

if [[ -f "${WRANGLER_FILE}" ]]; then
  if grep -q "id = \"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\"" "${WRANGLER_FILE}"; then
    echo "[fail] edge/wrangler.toml still has placeholder KV namespace id"
    fail=1
  else
    echo "[ok] wrangler KV namespace id looks configured"
  fi
else
  echo "[fail] missing edge/wrangler.toml"
  fail=1
fi

if [[ ${fail} -ne 0 ]]; then
  echo "[preflight] FAILED"
  exit 1
fi

echo "[preflight] PASSED"
