#!/usr/bin/env bash
# Three independent paired repetitions. Planning/reporting never executes the robot.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$project_dir"
root="${HUMANOID_REPETITIONS_ROOT:-development/humanoid_repetitions3_20261024_v1}"
case "${1:---dry-run}" in
  --dry-run)
    [[ $# -le 1 ]] || exit 2
    echo "3 new independent repetitions: AFS 7 + Random 7 each; 42 total episodes."
    echo "Each arm: baseline 1 + one-axis 3 + two-axis 3."
    echo "Luna/OpenRouter; max_tokens 128000; robot calls 20/episode; HTTP 600s."
    echo "Upper bounds: 840 robot API calls + 27 AFS proposals."
    echo "RESULTS=$project_dir/$root"
    exit 0
    ;;
  --status)
    [[ $# -eq 1 ]] || exit 2
    exec uv run --no-sync python tools/report_humanoid_repetitions.py --root "$root"
    ;;
  --live) [[ $# -eq 1 ]] || exit 2 ;;
  *) echo "Usage: bash tools/run_humanoid_repetitions.sh [--dry-run|--status|--live]" >&2; exit 2 ;;
esac
[[ -f "$root/repetitions.json" ]] || { echo "Frozen repetition plan is missing." >&2; exit 2; }
seed_lines="$(uv run --no-sync python tools/humanoid_repetition_seeds.py --root "$root" --read)"
mapfile -t seeds <<< "$seed_lines"
[[ ${#seeds[@]} -eq 3 ]] || { echo "Expected three stored seeds." >&2; exit 2; }
exec 9>"$root/.run.lock"
flock -n 9 || { echo "Another repetition batch is active." >&2; exit 2; }
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
overall_status=0
for seed in "${seeds[@]}"; do
  campaign="$root/seed_$seed"
  [[ -f "$campaign/manifest.json" ]] || { echo "Missing prepared campaign $seed" >&2; exit 2; }
  echo "=== 반복 seed=$seed: AFS 7회 + Random 7회 ==="
  (
    sleeper=""
    trap 'if [[ -n "$sleeper" ]]; then kill "$sleeper" 2>/dev/null || true; wait "$sleeper" 2>/dev/null || true; fi; exit 0' TERM INT
    while true; do
      sleep 30 &
      sleeper=$!
      wait "$sleeper" || exit 0
      sleeper=""
      echo "진행 중: 반복 seed=$seed (실행 또는 결과 검증)"
    done
  ) &
  heartbeat_pid=$!
  if uv run --no-sync python -u tools/run_paired_discovery.py run \
    --campaign "$campaign" --live --max-new-attempts 14 --max-new-afs-requests 9; then
    echo "REPETITION seed=$seed RUN_FINISHED (completion verified in summary)"
  else
    code=$?
    echo "REPETITION seed=$seed STOPPED exit=$code; no automatic retry" >&2
    if [[ "$code" -eq 130 || "$code" -eq 143 ]]; then exit "$code"; fi
    overall_status=$code
  fi
  cleanup
  heartbeat_pid=""
  uv run --no-sync python tools/report_humanoid_repetitions.py --root "$root"
done
if uv run --no-sync python tools/report_humanoid_repetitions.py --root "$root" --require-all; then
  echo "ALL_REPETITIONS=COMPLETE"
else
  overall_status=$?
fi
exit "$overall_status"
