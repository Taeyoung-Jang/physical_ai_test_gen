#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
exec .venv/bin/python -u tools/run_robot_arm_reproducibility.py run --live "$@"
