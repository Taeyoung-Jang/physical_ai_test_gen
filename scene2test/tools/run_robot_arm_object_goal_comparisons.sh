#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
case "${1:-}" in
  "") exec .venv/bin/python -u tools/run_robot_arm_task_comparisons.py plan ;;
  --status) exec .venv/bin/python -u tools/run_robot_arm_task_comparisons.py status ;;
  --live) exec .venv/bin/python -u tools/run_robot_arm_task_comparisons.py run --live ;;
  *) echo "Usage: bash tools/run_robot_arm_object_goal_comparisons.sh [--live|--status]" >&2; exit 2 ;;
esac
