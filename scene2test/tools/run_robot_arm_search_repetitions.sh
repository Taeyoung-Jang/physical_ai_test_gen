#!/usr/bin/env bash
# Dry-run by default; explicit --live runs the three new paired search sets.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
exec .venv/bin/python -u tools/run_robot_arm_search_repetitions.py "$@"
