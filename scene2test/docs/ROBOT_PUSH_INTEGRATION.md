Current timeout update: the goal agent now defaults to HTTP read 90s and runner
wall deadline 120s, configurable with `--response-timeout`. See
[ROBOT_REQUEST_TIMING.md](ROBOT_REQUEST_TIMING.md). Earlier 30s settings below describe
the historical runs, not the current goal-agent default.

# Opt-in robot goal-agent push integration (v3)

Enable the experimental short push executor explicitly:

```bash
uv run python tools/run_robot_goal_agent.py --live --model gpt-6-astra --max-calls 10 --max-seconds 120 --enable-push
```

Without `--enable-push`, the original navigation-only policy/schema/controller remains
selected. With it, GPT receives the typed `push_object` action alongside the existing
tools, full geometry/current camera, capability bounds and measured action history.
The existing 30s response deadline is unchanged. `--max-seconds` remains simulation
time, including inference waits; a push needs 21s remaining (18s skill + 3s handoff).
No paid calls were made during implementation.

## Decision and execution boundary

GPT selects approach, object and desired object-center XY. No route, placement target,
or ordering is supplied by the evaluator. Executor preflight checks fresh object pose,
upright supported geometry, approach alignment, target bounds and remaining time.
Rejected requests return a reason without executing a push. Full preconditions are
in the prompt and [skill documentation](ROBOT_PUSH_SKILL.md).

Only `clear_box_geom` is currently supported. Real contact dynamics through CUDA gait
and arm IK/PD actuators move it; no object teleport/attachment/external forces. The
controller starts once per run and retains physical state, ONNX history and gait phase
across navigation/push. During the skill, only hands contacting the selected box are
exempted; all other world contact guards remain active. Force limit is 120N per contact.
Release is required before restoring neutral arms over a 3s pose-hold handoff with the
contact exemption removed. A release failure terminates the episode, not another GPT call.
The opt-in controller differs from the navigation-only baseline and has a separate
protocol version, controller condition and source hashes.

`skill_NNN.json` records measured displacement, target error, contact time/force,
release and handoff outcome. `contacts.jsonl` records relevant contacts. Next camera
observation/map geometry is taken from the actual updated MuJoCo state. The planner
uses that state on GPT's next request. Existing diagnostics, video/GIF and manifest remain.

## Validation and limits

GPU integration tests use a deterministic mock policy, not GPT: near-box initial
setup and original-spawn approach both exercised push, release, neutral handoff,
updated geometry/planner and subsequent navigation. The original-spawn test requests
a short raw movement after navigation; that ordering exists ONLY in the test policy.
The production GPT policy is not given those test targets or instructions.

Runs under `/workspace/g1_failure/runtime/robot_push_integration/`:

- `20260918T171951_946630Z`: explicit near-box setup, ~8.08cm displacement.
- `20260918T172035_120683Z`: original x=1 spawn, ~8.07cm displacement; target XY error ~2.64mm.

Both pass physical skill and handoff checks; neither clears the full blocked corridor
or proves autonomous GPT success. Live acceptance of the extended API schema is not
yet tested; mock transport/schema validation passed. Short forward pushing is not
sideways placement, grasp/carry or jumping. Self-collision classification remains absent.

The structured action envelope follows official nested-union schema guidance:
https://developers.openai.com/api/docs/guides/structured-outputs

Reproduce GPU tests without API calls:

```bash
MUJOCO_GL=egl SIM_SERVER_ONNX_PROVIDER=cuda RUN_ROBOT_PUSH_GPU=1 uv run pytest tests/test_robot_push_integration.py -k gpu -q -s
```

## Follow-up GPU integration verification

The first original-spawn run's post-push plan/navigation queries returned
`blocked_endpoint`: the robot remained inside the planner's inflated box clearance.
This was not successful subsequent path following. Additional mock-only tests include
a short reverse action after handoff to validate real gait recovery. Production GPT
has no prescribed reverse action; it chooses its own response to this feedback.

Second pair: `20260918T172437_765283Z` (near-box) and
`20260918T172520_953600Z` (original spawn). Both GPU tests passed (106.01s).
Full-goal planning still reports no_path; local navigation executes after retreat.
102 unit/regression tests passed in separate suites; 4 GPU-only tests skipped there.
Do not treat these tests as proof of goal-reaching or live-model success.
