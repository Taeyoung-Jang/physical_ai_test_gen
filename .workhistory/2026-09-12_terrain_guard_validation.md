# Terrain guard verification and isolated CUDA rerun

Date: 2026-09-12 UTC.

## Request and source state

Verify the user's manual worlds.py guard changes, legacy regressions, and continued
operation of the isolated terrain runner. Starting worktree was clean at commit
`a9a48481cc1f6f90e5131ccb1871acd52f317ddd`. The user's guards are present in
register_world (before any destination writes) and resolve_world (after bundle
validation). No changes were made to those functions, shared workers or services.

## Added regression coverage

Added scene2test/tests/server/test_terrain_guards.py:

- Four presets (flat terrain, ramp, stairs, low friction) reject legacy registration.
- Rejection leaves the server data root nonexistent and the original bundle valid.
- A manually constructed preexisting terrain registry entry cannot resolve for legacy
  execution, remains unchanged on disk, and still validates for isolated use.

Command from scene2test:

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_terrain_courses.py tests/client tests/server tests/test_procedural_world.py tests/test_scene_search.py tests/test_scene_search_runner.py -q
```

Result: **121 passed, 1 warning, 83.45 seconds**. Warning: existing Starlette/httpx
deprecation. This includes legacy staged path planning, world registration/corruption,
G1 model composition and navigation API probe checks. These tests are not a fresh
live-server GPU maze rollout or proof of a running production service.

`.venv/bin/ruff check tests/server/test_terrain_guards.py`: passed.
`git diff --check`: passed before recording this report.

## Isolated GPU smoke rerun

GPU observed: NVIDIA RTX PRO 4000 Blackwell; initially idle. No matching terrain/search/
simulation_server processes were found in the preflight process check. No service was
started or restarted. Each episode verified CUDAExecutionProvider and used the
existing unmodified suite:

`/workspace/g1_failure/runtime/terrain_scenes/20260908T212812_265801Z/suite.json`

```bash
PYTHONPATH=src .venv/bin/python tools/run_terrain_validation.py --suite /workspace/g1_failure/runtime/terrain_scenes/20260908T212812_265801Z/suite.json --names flat ramp stairs low_friction --duration 120 --speed 0.25
```

Output:
`/workspace/g1_failure/runtime/terrain_validation/20260912T155805_545977Z/summary.json`

| Scene | Job | Result |
|---|---|---|
| flat | job_184cf4b4747b41aca1942c68106f202b | GOAL_REACHED |
| ramp, 5 degrees | job_ee50b46e64074284b6888a69e977b6af | STUCK |
| stairs, 4 cm | job_0f35f06be6514f58927e5bb51b3e84a6 | COLLISION |
| low_friction, mu=0.15 | job_da97a977998e44298ca65da88ef086b6 | GOAL_REACHED |

Runner exited 0. All four were EVALUATED; 13 artifacts per episode are hash/size
verified, 52 total, including MP4, GIF and trajectory PNG. Existing evidence was not
overwritten. Media contents were not visually reviewed in this turn.

## Observations and limitations

- Flat: 29.925 simulation seconds, final goal distance 0.1982 m, no fall/collision.
- Ramp: STUCK at 34.42 s with no recorded fall/collision. Final base x=3.7662 m;
  ramp starts x=3.8 m. Last commanded forward speed was 0.24983 m/s while the last
  200 logged states spanned x=3.7599–3.7683 m. This is evidence of commanded motion
  without appreciable progress near the ramp entrance, not a proven policy-only cause.
- Stairs: COLLISION at 9.065 s without a fall. Contact records identify
  world_surface_2 at approximately x=4.40 m and penetration around 2.1 mm, but the
  robot geom name is null. The evaluator logs wall/robot or non-foot/support contacts;
  logs need stable geom IDs and body names to identify the actual robot part reliably.
  Do not label this a particular limb collision from current logs alone.
- Outcomes agree with previous smoke evidence. One rerun per fixed scene/seed is not
  a multi-seed capability estimate, a full terrain baseline, or an AFS comparison.

## Tool limitation and documentation correction

Default exec still fails with the bwrap user-namespace error. Approved escalated
commands worked for reads/tests/isolated simulation. apply_patch Add File succeeded
for the new test and this record. Updating TERRAIN_SCENES.md failed at the helper's
read stage; no alternate overwrite was attempted.

The statements in TERRAIN_SCENES.md and AGENTS.md that terrain registration guards
are still unapplied are now stale: the user-applied guards exist and are tested.
Full terrain integration into the common server remains unimplemented, and terrain
must continue using the isolated runner. This record supersedes only the old guard
status, not that integration boundary.

## Next bounded work

First improve unnamed-contact provenance (geom IDs/body names), then inspect/replay
the ramp entrance and stair contact to distinguish geometry/controller/evaluator
issues. Establish a frozen multi-condition/repeat terrain protocol before expanding
terrain AFS and making equal-valid-budget Random/Sobol/AFS comparisons.
