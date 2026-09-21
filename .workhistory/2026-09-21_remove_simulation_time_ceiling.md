# Remove mandatory 120-second simulation ceiling

User explicitly requested removing the 120s upper bound. Goal-agent CLI and runner
now default max_seconds=None: no simulation-time deadline. Explicit --max-seconds
accepts finite values>=3 without a120s ceiling; an explicit120 still requests120.
Internal infinity is used only for comparisons; protocol records JSON null and an
unlimited boolean plus budget source hash. CLI prints simulation=unlimited.

Preserved call count limit, per-call response deadlines, goal/policy termination,
contact/fall/numerical guards, fixed skill bounds and inference-time physics stepping.
No automatic retries, API calls or old evidence modifications. Longer runs can
produce more recording data. Documentation: ROBOT_SIMULATION_BUDGET.md.

Validation:72 passed,5 explicitly gated GPU tests skipped; Ruff/diff whitespace pass.
GPU smoke via normal CLI --enable-push --max-calls1 with no --max-seconds:
`/workspace/g1_failure/runtime/robot_goal_agent/20260921T142654_047186Z`.
Protocol max_simulation_s=null, simulation_time_unlimited=true; valid execution,
ended BUDGET_EXHAUSTED at the requested one-call limit,0 API calls. This short smoke
checks default wiring/serialization, not long-duration physical stability. Unit
tests verify absent limit and explicit121/600/3600-second acceptance.
