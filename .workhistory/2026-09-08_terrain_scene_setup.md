# 2026-09-08 — Configurable terrain scene setup (in progress)

## Request

Expand synthetic scenes for AFS experimentation: slopes, widths, friction, stairs,
different obstacle dimensions and other environmental variations. Preserve previous
results and distinguish scene generation from actual G1 traversability.

## Initial state and preservation

The previous scene-search pilot files and AGENTS/history updates were already staged.
They were not unstaged, committed or reverted. Independent g1-local-nav is untouched.
Runtime artifacts remain under /workspace/g1_failure/runtime. Existing services are not
restarted and their job queues are not used for the new isolated terrain runner.

## Implemented components

- New TerrainSpec/Surface model: analytic height surfaces, convex mesh export, versioned
  metadata, height/slope/friction maps, graph traversable_surface nodes and adjacency.
- Composable flat, ramp, stairs, low-friction, rough, box/slalom and bottleneck sections.
  Global/section width and friction, box XYZ dimension ranges, stair tread/count/height,
  ramp angle/run/landing and roughness amplitude/scale are configurable.
- YAML recipe plus random/Sobol scalar-parameter sampling; candidates rejected explicitly
  for overlap, unsupported terrain or disconnected configured planning paths.
- Dedicated terrain worker/metrics/validation runner: ground-relative fall detection,
  foot vs non-foot support contacts, mesh contact-slip measurements, CUDA, videos and logs.
  The common worker and navigation_worker were not changed.
- Legacy SceneSpec serialization/revision remains unchanged. Existing core/export/world
  helpers have additive terrain-loading/geometry dispatch work in the working tree.

## Safety/tool blockers

Partial apply_patch updates fail with the environment's bwrap namespace error. Whole-file
apply_patch replacement was accepted for some additive helper changes but rejected by
automatic review for the common worker, navigation worker and subsequently the world
loader protection change. These rejections were not bypassed through shell/Python writes.

Work was narrowed to new terrain-only files. **Server integration/registration guards are
unfinished and require approval for the shared worlds.py change. Do not register terrain
bundles with the existing navigation server.** Documentation marks this restriction.
This is not a completed common-server terrain integration.

## Initial tests and corrections

Initial terrain unit tests: 19 passed, one failed. The default slalom fixture had no
footprint-clear path at its original density. Expanded its length from 6 to 8 m and
reduced count from 4 to 3; this is a generator starter-fixture correction before GPU
validation, not alteration of a completed comparison experiment.

The initial generated suite is preserved at
/workspace/g1_failure/runtime/terrain_scenes/20260908T211804_953972Z (7 ready, 1 invalid).
After correcting graph generator-version metadata and the slalom preset, regenerated at
/workspace/g1_failure/runtime/terrain_scenes/20260908T212129_518083Z.

Physics tests include downward mesh rays matching analytic ramp heights and actual contact
friction .15 despite robot geom friction 1.0. Backing-floor collision is disabled so it
cannot mask low-friction support. Full regression and final scene generation are pending
completion at the time of this entry; results will be appended, not inferred.

## Final verified results before approval pause

- Final regression: **116 passed**, one existing Starlette/httpx deprecation warning.
  Command: `PYTHONPATH=src .venv/bin/pytest tests/test_terrain_courses.py tests/client tests/server tests/test_procedural_world.py tests/test_scene_search.py tests/test_scene_search_runner.py -q`.
- Targeted Ruff checks and git diff --check passed.
- All eight presets generated successfully. Final visible-mesh suite:
  `/workspace/g1_failure/runtime/terrain_scenes/20260908T212812_265801Z/suite.json`.
- Five-parameter scrambled Sobol sample (n=4, seed=42):
  `/workspace/g1_failure/runtime/terrain_scenes/20260908T213118_933150Z/suite.json`.
  Two ready scenes, two disconnected/invalid scenes recorded explicitly. No resampling,
  no conversion of invalid geometry into robot failure.
- Ground mesh group 3 was hidden by default MjvOption ([1,1,1,0,0,0]). Changed the new
  terrain module to visible group 2, updated ray-test mask and added a visibility assertion.
  The prior rendering evidence is preserved; it must not be presented as correct terrain
  visualization. Final standalone stairs rendering and corrected rollout frame inspected.
- During that test update a path-substitution mistake created a 131-byte error-text file at
  /workspace/g1_failure/tests/physical_ai_test_gen/scene2test/src/test_terrain_courses.py.
  Inspected and moved only that accidentally created file to
  /tmp/terrain_test_patch_path_error_20260908.txt. No user file was removed. Corrected the
  actual repository test file with explicit path and checked successful reads thereafter.

### Actual CUDA smoke runs

Initial (terrain meshes physically present but hidden in rendering):
`/workspace/g1_failure/runtime/terrain_validation/20260908T212355_800325Z/summary.json`.

| Scene | Execution | Task result |
|---|---|---|
| flat | valid CUDA | GOAL_REACHED |
| ramp (5 deg) | valid CUDA | STUCK |
| stairs (.04 m steps) | valid CUDA | COLLISION |
| low_friction (.15) | valid CUDA | GOAL_REACHED |

After display correction, repeated ramp and stairs:
`/workspace/g1_failure/runtime/terrain_validation/20260908T213044_968233Z/summary.json`.
The same termination classes recurred (STUCK / COLLISION). Both include visible terrain
in MP4/GIF, state/action/contact logs and reproduction. The final stair video is
`job_4934a1f018c84c03aea5e1a136550779/rollout.mp4` under that run.
Total six rollouts, 78 artifact hash/size checks. These smoke outcomes are not an AFS
comparison or proof of the intrinsic robot limits; controller/contact-model causes of
failures require investigation before making capability claims. No gait weights changed.

The new support-contact measurement produced actual contact samples (e.g. flat 26,000),
not the legacy plane-only placeholder zero. Default flat scene revision equality and
legacy tests passed. Shared worker.py and navigation_worker.py remain unchanged.

## Remaining blocker and handoff

Environment generation, recipes, sampling, 2.5D maps, rendering and isolated GPU checks
are available. **Do not claim the complete requested workflow is integrated into the
shared server or general AFS client.** Existing worlds.py has additive loading/composition
work, but the follow-up guard rejecting terrain registration/resolution on the legacy
navigation server was blocked by automatic review of whole-file replacement.

User approval is required to finish that limited worlds.py protection change while
preserving existing flat-scene behavior. Partial apply_patch is unavailable because of
the filesystem namespace error. Do not bypass the denial with alternative write tools.
No active terrain simulation processes remain at handoff.
