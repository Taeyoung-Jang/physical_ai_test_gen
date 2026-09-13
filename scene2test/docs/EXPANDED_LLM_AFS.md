# Expanded terrain-space AFS v2

Implemented 2026-09-13. Opt-in extension; `run_llm_afs.py` v1 and all common-server
workers remain unchanged. This generates hypotheses and executable scene bundles,
not measured failure cases. It does not modify the G1 controller.

## Controllable scene space

`config/llm_afs_expanded.yaml` defines approved layouts and typed domains. Each layout
is a complete `generate_course` recipe; adding a template permits another ordering or
combination of the existing segment kinds (up to 12 segments, 16 templates).
The model chooses templates, not arbitrary code, XML, or new geometry primitives.

| Factor | Supported controls |
| --- | --- |
| General | Course width, floor/segment friction, generator seed |
| Ramp | Angle, length, landing length, segment width/friction |
| Stairs | Integer step count, step height, tread depth, landing |
| Roughness | Amplitude, cell length, section length |
| Bottleneck | Gap width, section length |
| Obstacles | Integer count; random/slalom pattern; each x/y/z component of minimum/maximum size; section length |
| Course structure | User-approved segment combinations/order via named templates |

Paths must point to explicitly present fields. For example `segments.1.size_max_m.2`
controls the upper bound on obstacle height; it is not the exact height of every box.
Obstacle positions and roughness realizations change through the scene seed. Direct
per-object xyz/rotation, dynamic obstacles, cross-slopes, sensor corruption, arbitrary
maze/room topology editing, and robot dynamics mutations are **not added here**.

Domains have `kind: float|int|choice`, required `low`, `high`, and `choices`.
Numeric domains use empty choices. Choice domains use null bounds and currently select
`random`/`slalom` obstacle patterns. Integer bins include both endpoints. Jointly invalid
combinations (overlap, blocked map, incompatible size bounds, excessive geometry limits)
are retained as `INVALID_SCENE`; no silent retry or robot-failure label is assigned.

The example includes ramp→obstacles, obstacles→ramp, stairs→bottleneck, rough→friction.
Generator limits and static path checks are assumptions, not certified gait capabilities.

## Task and proposal contracts

The proposal contains `failure-space-proposal-v2`, exact `config_sha256`, and spaces
with `layout`, `hypothesis`, and narrowed typed `domains`. Unspecified axes continue
sampling their original allowed domains. Hosts reject unknown paths/templates and
out-of-bounds proposals. Robot, actual GT-map/GT-pose policy, and evaluator stay frozen.

`endpoint_policy: generated_course_end` explicitly defines the task as reaching the end
of each generated course. Counts/lengths can change course length and goal coordinates.
Spawn/goal are recorded in every generated candidate and bundle. This is **not** a
fixed endpoint experiment. Use `fixed` to reject layouts/candidates whose endpoints
differ from `condition.course`. Duration and speed stay fixed, so length is itself a
potential confound: compare within layouts/length strata when interpreting failures.

Responses API uses the existing explicit-call provider and a separate v2 prompt with
strict JSON schema. The local schema supports mixed-type domains; real model output
quality/latency/cost remain unvalidated. Default preparation and offline/baseline modes
make no API calls, even if an API key is present. Only `--live` makes one paid call.
OpenAI Structured Outputs reference: https://developers.openai.com/api/docs/guides/structured-outputs

## Active exploration and budgets

The mixed scheduler repeats four attempt slots:

1. Full allowed space, round-robin layout coverage.
2. Full allowed space, continuing layout coverage.
3. LLM-proposed joint space, cycling proposed spaces.
4. Verified failure neighborhood; otherwise another full-space attempt.

Neighborhood numeric radius is 15% of original domain width (at least one integer
step), clipped to allowed bounds. Scene seed and categorical choices continue full
exploration. Multiple axes vary jointly; this can expose interactions but does **not**
estimate causal factor contributions. There is no learned acquisition/calibrated
failure probability or automatic hypothesis-quality ranking in this extension.

Random/Sobol baselines use the same compiler, domains, layout round-robin and checks,
without LLM narrowing or local failure search. Sobol uses one reproducible stream per
layout; discrete variables are binned, not physical equal-spacing of obstacles.

`--samples` is an **attempt budget**, not a valid-rollout budget. Invalid and duplicate
scenes remain in `suite.json`; only READY scenes should reach the isolated runner.
Revision duplicates are skipped within a round and against imported observations.
There is no semantic geometry deduplication across different seeds, automatic duplicate
failure-mechanism clustering, or cross-round history of unevaluated/invalid attempts.
Do not claim increased distinct failure mechanisms from a higher raw failure count.
An equal-valid-rollout comparison driver and multi-seed measured campaign remain next work.

## Commands

Run from `scene2test` using `uv run python` (or `.venv/bin/python`).

```bash
# Prepare request/context only; no key needed.
uv run python tools/run_expanded_afs.py
# Exercise the compiler with an explicit NON-LLM fixture.
uv run python tools/run_expanded_afs.py --offline-demo --samples 12 --seed 17
# Same configurable scene space, no LLM.
uv run python tools/run_expanded_afs.py --baseline random --samples 12 --seed 17
uv run python tools/run_expanded_afs.py --baseline sobol --samples 12 --seed 17
# After setting OPENAI_API_KEY locally; ONE paid call, no GPU execution.
uv run python tools/run_expanded_afs.py --live --samples 12 --seed 17
```

Output defaults to `/workspace/g1_failure/runtime/llm_afs_expanded/<UTC-run>/`.
It includes config/context/request/protocol, proposal, suite/status and scene bundles
(SceneSpec, SceneGraph, navigation map, MuJoCo XML, preview and terrain-map PNG).
Offline scene creation produces **no rollout video/GIF**; the existing isolated robot
runner records rollout artifacts/video when separately executed:

```bash
uv run python tools/run_terrain_validation.py --suite /absolute/prior-run/suite.json --duration 120 --speed 0.25
uv run python tools/run_expanded_afs.py --feedback /absolute/prior-run /absolute/runner-run/summary.json --live
```

Use duration/speed from the frozen config. Never register these terrain bundles in the
legacy navigation server. Feedback reuses v1 request/resource/code/artifact hash checks,
requires actual CUDA execution identity, then attaches the originating layout. Only
EVALUATED robot failures seed local search; infrastructure/indeterminate results do not.
Import is trusted-local integrity checking, not authentication against malicious writers.
Maximum accumulated feedback is 64 observations; no silent truncation. No autonomous
GPU/API loop is launched. v1 and v2 feedback configs are intentionally incompatible.

## Validation evidence

Offline seed-17 fixture: 12 attempts, 10 valid bundles, 2 disconnected-map rejections.
All four template families appeared. This is compiler evidence, not robot performance.
Unit tests cover typed bounds, layout/path rejection, closed JSON schema, deterministic
Random/Sobol/mixed sampling, actual bundle regeneration, endpoint semantics, verified
synthetic feedback, artifact tampering, and zero-network default CLI behavior.
