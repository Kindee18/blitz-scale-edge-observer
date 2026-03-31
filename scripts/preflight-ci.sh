#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WRANGLER_FILE="${ROOT_DIR}/edge/wrangler.toml"

echo "[preflight-ci] running"

required_cmds=(bash python3 terraform)
for c in "${required_cmds[@]}"; do
  if ! command -v "${c}" >/dev/null 2>&1; then
    echo "[preflight-ci][fail] missing command: ${c}"
    exit 1
  fi
done

if [[ ! -f "${WRANGLER_FILE}" ]]; then
  echo "[preflight-ci][fail] edge/wrangler.toml missing"
  exit 1
fi

if grep -q "id = \"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\"" "${WRANGLER_FILE}"; then
  echo "[preflight-ci][fail] placeholder KV namespace id in edge/wrangler.toml"
  exit 1
fi

echo "[preflight-ci][ok] wrangler config present"

if [[ "${CHECK_AWS_ROLE_ARN:-false}" == "true" ]]; then
  if [[ -z "${AWS_ROLE_ARN:-}" ]]; then
    echo "[preflight-ci][fail] AWS_ROLE_ARN is required"
    exit 1
  fi
  echo "[preflight-ci][ok] AWS_ROLE_ARN set"
fi

if [[ "${CHECK_CF_API_TOKEN:-false}" == "true" ]]; then
  if [[ -z "${CF_API_TOKEN:-}" ]]; then
    echo "[preflight-ci][fail] CF_API_TOKEN is required"
    exit 1
  fi
  echo "[preflight-ci][ok] CF_API_TOKEN set"
fi

echo "[preflight-ci] PASSED"
