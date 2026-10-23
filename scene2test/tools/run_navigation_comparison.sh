#!/usr/bin/env bash
# A prepared frozen campaign only. Never initialize, retry or resume exclusions implicitly.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
campaign_dir=/workspace/g1_failure/runtime/paired_discovery/luna_navigation_domain_20261021_v1
command=(uv run --no-sync python tools/run_paired_discovery.py run
  --campaign "$campaign_dir" --live --max-new-attempts 48 --max-new-afs-requests 24)
case "${1:---dry-run}" in
  --dry-run)
    if [[ $# -gt 1 ]]; then exit 2; fi
    printf 'Working directory: %s\n' "$project_dir"
    printf 'Paid upper bound: 48 episodes / 480 robot policy calls / 24 AFS requests.\n'
    printf 'Valid target: 36 episodes; navigation subdomain only; no superiority guarantee.\n'
    printf '%q ' "${command[@]}"
    printf '\n'
    ;;
  --live)
    if [[ $# -ne 1 || ! -f "$campaign_dir/manifest.json" ]]; then
      printf 'Expected one --live argument and a prepared campaign.\n' >&2
      exit 2
    fi
    cd -- "$project_dir"
    printf 'LOG=%s/run.log\n' "$campaign_dir"
    "${command[@]}" 2>&1 | tee -a "$campaign_dir/run.log"
    ;;
  *) printf 'Usage: bash tools/run_navigation_comparison.sh [--dry-run|--live]\n' >&2; exit 2 ;;
esac
