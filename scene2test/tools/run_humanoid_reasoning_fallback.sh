#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$project_dir"
root="development/humanoid_reasoning_fallback3_20261024_v1"
mode="${1:---dry-run}"
[[ $# -le 1 ]] || exit 2
case "$mode" in
  --dry-run)
    echo "Robot Luna: high -> medium -> low -> none, verified length only; reduced effort persists."
    echo "Every generation counts toward 20 calls/episode; max_tokens=128000."
    echo "HTTP read=600s; wall deadline=1200s; AFS proposer remains medium."
    echo "One new control + three new AFS7/Random7 sets = 43 episodes maximum."
    echo "Three unique random seeds are drawn once and saved before execution; resume keeps them."
    echo "Upper bound: 860 robot calls + 27 AFS requests; old results preserved."
    exit 0 ;;
  --status)
    [[ -f "$root/repetitions.json" ]] || { echo "New fallback campaigns not prepared yet; no API calls."; exit 0; }
    HUMANOID_REPETITIONS_ROOT="$root" bash tools/run_humanoid_repetitions.sh --status
    exit $? ;;
  --live) ;;
  *) echo "Usage: bash tools/run_humanoid_reasoning_fallback.sh [--dry-run|--status|--live]" >&2; exit 2 ;;
esac
mkdir -p -- "$root"
exec 8>"$root/.prepare.lock"
flock -n 8 || { echo "Another fallback batch is active." >&2; exit 2; }
uv run --no-sync python tools/humanoid_repetition_seeds.py --root "$root"
control="$root/control"
if [[ ! -e "$control" ]]; then
  uv run --no-sync python -u tools/run_robot_goal_agent.py \
    --live --api-provider openrouter --model openai/gpt-6-luna \
    --scene-config config/humanoid_assessment_baseline_timeout600.json \
    --enable-push --max-calls 20 --navigation-completion goal_dwell_v1 \
    --response-timeout 600 --run-dir "$control"
fi
uv run --no-sync python - "$root" "$control" <<'PY'
import json
import sys
from pathlib import Path

from failure_client.evaluation.goal_run_reader import read_goal_run
from failure_client.evaluation.research_records import RunInput
from failure_client.experiments.local_goal_adapter import atomic_json
from failure_client.experiments.paired_discovery import PairedDesign, PairedDiscovery, paired_plan
from llm_afs.behavior import digest
from robot_vlm.reasoning_fallback import contract
import runpy

root, control = (Path(value).resolve() for value in sys.argv[1:])
record = read_goal_run(RunInput(path=str(control)))
if record.status != "VALID" or record.task_outcome != "PASS":
    raise SystemExit("Fallback control is not a verified PASS; preserved, never rerun automatically")
p = json.loads((control / "protocol.json").read_text())
if (p.get("reasoning_fallback") != contract(True) or p["max_calls"] != 20
        or p["response_deadline_wall_s"] != 1200 or p["http_read_timeout_s"] != 600
        or p["model"] != "openai/gpt-6-luna" or p.get("api_provider") != "openrouter"):
    raise SystemExit("Control fallback/model/budget contract changed")
rows = []
seeds = runpy.run_path("tools/humanoid_repetition_seeds.py")["read"](root)
for seed in seeds:
    data = json.loads(Path("config/humanoid_replication_75101.json").read_text())
    data["seeds"] = [seed]
    design = PairedDesign.model_validate(data)
    frozen = paired_plan([control], design)
    destination = root / f"seed_{seed}"
    if destination.exists():
        if json.loads((destination / "manifest.json").read_text()) != frozen:
            raise SystemExit("Existing frozen repetition differs; no reset")
        for arm in PairedDiscovery(destination).arms():
            arm._fresh()
    else:
        PairedDiscovery.create(destination, frozen)
    rows.append({"seed": seed, "directory": destination.name, "manifest_sha256": frozen["sha256"]})
    print(f"FALLBACK_REPETITION_READY seed={seed}; no old outcomes imported", flush=True)
value = {"schema_version": "humanoid-reasoning-fallback-repetitions-v1", "repetitions": rows,
         "episodes": 42, "robot_api_call_cap": 840, "afs_request_cap": 27,
         "additional_control_episodes": 1, "overall_robot_call_cap": 860,
         "reasoning_fallback": contract(True), "afs_reasoning": "medium",
         "old_outcomes_imported": False, "control": str(control)}
bundle = {"value": value, "sha256": digest(value)}
file = root / "repetitions.json"
if file.exists() and json.loads(file.read_text()) != bundle:
    raise SystemExit("Frozen batch differs; never overwrite")
if not file.exists():
    atomic_json(file, bundle)
PY
HUMANOID_REPETITIONS_ROOT="$root" bash tools/run_humanoid_repetitions.sh --live
