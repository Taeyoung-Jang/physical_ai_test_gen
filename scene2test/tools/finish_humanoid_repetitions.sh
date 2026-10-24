#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
heartbeat_pid=""
cleanup() {
  if [[ -n "$heartbeat_pid" ]]; then
    kill "$heartbeat_pid" 2>/dev/null || true
    wait "$heartbeat_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ "${1:-}" == "--live" ]]; then
  (
    sleeper=""
    trap 'if [[ -n "$sleeper" ]]; then kill "$sleeper" 2>/dev/null || true; wait "$sleeper" 2>/dev/null || true; fi; exit 0' TERM INT
    while true; do
      sleep 30 &
      sleeper=$!
      wait "$sleeper" || exit 0
      sleeper=""
      echo "진행 중: 휴머노이드 미완료 실험 재개 (실행 또는 검증 중)"
    done
  ) &
  heartbeat_pid=$!
fi
uv run --no-sync python -u tools/finish_humanoid_repetitions.py "$@"
