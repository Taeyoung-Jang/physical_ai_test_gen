#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
exec .venv/bin/python tools/run_robot_arm_free_pair_search.py run --live \
  --output experiments/robot_arm_libero/free_pair_continuation_v5 \
  --max-new-attempts 23
