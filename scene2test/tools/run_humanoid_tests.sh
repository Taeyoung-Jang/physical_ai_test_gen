#!/usr/bin/env bash
# New 600-second timing condition; existing assessment archives stay unchanged.
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$project_dir"

mode="${1:-both}"
case "$mode" in
  afs|random|both) ;;
  -h|--help)
    echo "Usage: bash tools/run_humanoid_tests.sh [afs|random|both]"
    echo "Default: both (AFS first, then Random); ten attempts each."
    echo "HTTP wait: 600s; robot response deadline: 653s."
    echo "First invocation also executes one shared baseline control (up to ten robot API calls)."
    exit 0
    ;;
  *)
    echo "Usage: bash tools/run_humanoid_tests.sh [afs|random|both]" >&2
    exit 2
    ;;
esac
if (( $# > 1 )); then
  echo "Only one mode argument is supported." >&2
  exit 2
fi

assessment_root="development/humanoid_timeout600_20261023_v2"
control="$assessment_root/control"
mkdir -p -- "$assessment_root"
# Lock the whole wrapper, including its shared control; no concurrent dispatch.
exec 9>"$assessment_root/.run.lock"
if ! flock -n 9; then
  echo "Another humanoid timeout600 invocation is active." >&2
  exit 2
fi

echo "=== HTTP wait 600s / robot response deadline 653s / AFS proposal wait 600s ==="
if [[ ! -e "$control" ]]; then
  echo "=== New timing condition: shared baseline control (one additional episode) ==="
  uv run --no-sync python -u tools/run_robot_goal_agent.py \
    --live --api-provider openrouter --model openai/gpt-6-luna-pro \
    --scene-config config/humanoid_assessment_baseline_timeout600.json \
    --enable-push --max-calls 10 --navigation-completion goal_dwell_v1 \
    --response-timeout 600 --run-dir "$control"
fi

# An incomplete/failed existing control is never deleted or automatically rerun.
uv run --no-sync python - "$control" <<'PY'
import json
import sys
from pathlib import Path

from failure_client.evaluation.goal_run_reader import read_goal_run
from failure_client.evaluation.research_records import RunInput

root = Path(sys.argv[1]).resolve()
record = read_goal_run(RunInput(path=str(root)))
if record.status != "VALID" or record.task_outcome != "PASS":
    raise SystemExit("Control is not a verified PASS; stopped without retry/reset: " + str(root))
protocol = json.loads((root / "protocol.json").read_text())
if protocol["http_read_timeout_s"] != 600 or protocol["response_deadline_wall_s"] != 653:
    raise SystemExit("Control timing differs from 600/653 seconds")
print("CONTROL=VALID PASS; old outcomes are not imported into assessment histories", flush=True)
PY

run_assessment() {
  local method="$1"
  local runner="$2"
  local config="$3"
  local destination="$assessment_root/$method"
  if [[ ! -e "$destination" ]]; then
    uv run --no-sync python "$runner" init \
      --config "$config" --run "$control" --output-dir "$destination" || return $?
  fi
  echo "=== $method: ten-attempt assessment, HTTP wait 600s ==="
  uv run --no-sync python -u "$runner" run --assessment "$destination" --live
}

overall_status=0
if [[ "$mode" == afs || "$mode" == both ]]; then
  if run_assessment afs tools/run_humanoid_assessment.py \
    config/humanoid_vulnerability_10_pro_timeout600.json; then
    echo "AFS_STATUS=complete"
  else
    overall_status=$?
    echo "AFS_STATUS=stopped; exit=$overall_status (saved evidence preserved)" >&2
  fi
fi

if [[ "$mode" == random || "$mode" == both ]]; then
  if run_assessment random tools/run_humanoid_random_assessment.py \
    config/humanoid_random_vulnerability_10_pro_timeout600.json; then
    echo "RANDOM_STATUS=complete"
  else
    overall_status=$?
    echo "RANDOM_STATUS=stopped; exit=$overall_status (saved evidence preserved)" >&2
  fi
fi
echo "RESULTS=$project_dir/$assessment_root"
exit "$overall_status"
