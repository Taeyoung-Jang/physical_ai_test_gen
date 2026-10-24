# LIBERO Object / Goal single-episode probes

User-requested development check of two tasks beyond the existing Spatial task.
Tasks and seeds were selected before execution, without filtering by outcomes.

| Suite | Task | Seed | Maximum control steps |
|---|---|---:|---:|
| Object | Pick up the butter and place it in the basket | 76001 | 300 |
| Goal | Open the middle drawer of the cabinet | 76002 | 300 |

Each task uses its own suite-specific `nvidia/GR00T-N1.7-LIBERO` checkpoint at
revision `2ea293aa20ba7cf5bbf3ba17a5fbcb1a01cbfe21`. The existing Spatial
checkpoint and all existing experiment sources and results are preserved.
Only inference files were downloaded for the two additional suites (about
13.83 GB total); training optimizer states were omitted.

Configuration: `config/robot_arm_object_goal.json`.
Output: `experiments/robot_arm_libero/object_goal_smoke_20261024_v1`.
The tool binds source, task BDDL, configuration and model hashes before launch,
executes one episode per task sequentially, and preserves native results, videos,
logs and evidence hashes. Existing output is never replayed automatically.
Errors or missing outcomes are INCONCLUSIVE and stop the invocation without
retry or replacement. There are no environment mutations or AFS requests.

From `scene2test`, inspect saved results with:

```bash
.venv/bin/python tools/run_robot_arm_object_goal.py status
```

The execution command is `.venv/bin/python -u tools/run_robot_arm_object_goal.py run --live`.
If output already exists, use status; do not delete/reset it to rerun.

Success is the upstream LIBERO native `check_success` result. The rollout stops
on success or the 300-step cap and uses action chunks of 8. Sampling uses the
upstream seeded reset, rather than the official fixed initial-state benchmark
protocol. One episode per task checks basic execution only; it does not estimate
suite success rates or establish AFS/Random performance. These probes do not
extend the existing bowl-specific obstacle search to arbitrary tasks.

## Observed results (2026-10-24)

Both first executions completed with native LIBERO PASS, with no retries or
replacement: Object butter-in-basket at 151 control steps, Goal middle-drawer
opening at 117 control steps. Each used the matching suite checkpoint. Result
JSON, MP4, logs and hash manifests remain in the output directory above.
These are two successful basic task checks, not an AFS comparison or a suite
success-rate estimate.
