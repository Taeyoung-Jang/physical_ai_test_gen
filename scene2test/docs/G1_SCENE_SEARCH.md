# Scene-based G1 search pilot

## Scope and execution

Run from `scene2test`:

```bash
PYTHONPATH=src .venv/bin/python tools/run_scene_search.py
# Resume without duplicate submission (same source/resources/server required):
PYTHONPATH=src .venv/bin/python tools/run_scene_search.py --resume /workspace/g1_failure/runtime/scene_search/RUN_DIRECTORY
```

Requires the navigation server on localhost:8001 and its local registry at
`/workspace/g1_failure/runtime/navigation_server`. This trusted local runner registers
derived immutable bundles and submits the existing `navigation@1.0` HTTP contract.
It does not add remote scene-upload privileges or broaden the server intervention API.
The existing durable failure_client orchestrator and its built-in method registry are
unchanged: this is a separate scene-bundle pilot, not a new general-purpose client plugin.
Legacy Panda AFS and `g1-local-nav` are untouched.

## Fixed protocol (`g1-scene-search-v1`)

- Base scene: the previously validated `obstacle` navigation fixture.
- Editable SceneGraph object: `obstacle_0`; translate world X by [-2,2] m and Y by
  [-2.4,2.4] m. Geometry dimensions, walls, spawn, goal and robot remain fixed.
- Reject nonfinite/out-of-range parameters, overlapping solid geometry, outside-floor
  placement and disconnected navigation maps. Rejection is NOT a robot failure.
- Regenerate SceneSpec, SceneGraph, navigation map and XML from the same derived geometry.
  Registry ingestion verifies revisions and checksums; the worker composes the G1 model.
- Ground-truth map is updated for each candidate. This tests navigation/control under
  environmental variation, not perception failure or unexpected obstacles on a stale map.
- Methods: independent Random, scrambled Sobol, sequential adaptive AFS.
- Each method receives 8 **valid evaluated** rollouts by default, at most 40 proposals.
  Early cap exhaustion is reported incomplete and exits nonzero. Invalid geometry and
  execution errors do not consume the valid budget or train the surrogate.
- Same seed 20260906, 0.3 m/s command, 120 s maximum duration, 1 s settling and existing
  goal/stuck tolerances. CUDA provider and actual scene revision are verified from results.
- All rollouts request MP4/GIF; the server retains videos, trajectories, contacts, physics
  XML and reproduction metadata. The client verifies all artifact checksums and sizes over
  HTTP, retaining references instead of making redundant copies of large videos.

## Adaptive search, not a fixed candidate replay

AFS starts with Sobol until four valid observations. After each valid result it rebuilds
64 ExtraTrees regressors from the observed 2D offsets and scalar search utility. It scores
512 random candidates by `mean - ensemble_std - 0.1 * distance_to_nearest_proposal`.
The minimum score is executed, observed, then the next pool is scored again.
Invalid proposals enter the novelty calculation, but never the training targets.
The complete JSON journal and deterministic per-attempt RNG recreate the sampler; no
pickle checkpoint or imported precomputed failure candidates are used.

Utility is deliberately labeled a **search heuristic**, not the legacy six physical
margins or a calibrated failure probability:

- Success: `max(0.001, 1 - elapsed_simulation_s / maximum_duration_s)`.
- Failure: `-1 - min(goal_distance_m / 10, 1)`.
- Invalid execution, missing or nonfinite facts: no observation.

All valid failures rank below successes. Successful but slow episodes expose low time
slack; unsuccessful episodes expose residual goal distance. This discontinuous utility
is an initial surrogate target, not a claim of physical robustness certification.

## Evidence and interpretation

`/workspace/g1_failure/runtime/scene_search/<timestamp>/` contains a frozen protocol with
code/resource hashes, atomic journal, per-attempt mutations/requests/results/verified
artifact manifests, derived world bundles, `summary.json` and `report.md`.
The server artifacts remain under `runtime/navigation_server`.

Counts refer to failing rollouts, not unique failure mechanisms. Report valid budget,
invalid-scene count, execution errors, first failure index and actual adaptive rollouts.
Single-seed, small-budget results do not establish statistical superiority; zero failures
means none were found in the sampled domain, not universal safety. Method-order timing
is not randomized and must not be used to claim wall-clock speedup. Simulator seed is
fixed across methods, but execution determinism is best-effort.

The current composed box floor does not support the old plane-only slip metric; do not
interpret its zero/default values as measured absence of slip. More seeds, domains,
continuous clearance/stability margins and integration into the general client protocol
are follow-up work, not completed capabilities of this pilot.

After the run finishes, create a non-overwriting audit and mutation-space plot:

```bash
PYTHONPATH=src .venv/bin/python tools/review_scene_search.py /workspace/g1_failure/runtime/scene_search/RUN_DIRECTORY
```

The reviewer replays every sampler proposal from prior observations, checks frozen source
hashes against worker reproduction, re-verifies local artifacts, and compares the common
Sobol/AFS cold-start repeats. Outputs are in the run's new `review/` directory. A source
change or pending attempt is an audit error, not a reason to silently skip validation.
