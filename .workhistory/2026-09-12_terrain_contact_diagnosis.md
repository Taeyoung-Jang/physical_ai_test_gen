# Terrain contact provenance and failure diagnosis

Date: 2026-09-12 UTC. User requested contact logging improvement and ramp/stair diagnosis.
Starting worktree was clean. Existing user-applied server guards were preserved.

## Delivered and blocked scope

Added tools/analyze_terrain_contacts.py: reads saved composed model and 20 Hz state
samples, computes mj_forward contacts, writes separate timestamped diagnostic JSONL
with geom IDs/names, body IDs/names, contact normals, positions and penetration.
Unnamed robot geoms retain usable body identity. IDs are local to the hashed model,
not stable across different scene revisions. Reports explicitly distinguish sampled
geometry reconstruction from dynamics replay. Existing jobs are never overwritten.

Added tools/replay_terrain_diagnostic.py: independent unrendered CUDA replay using the
saved model, request, current gait adapter and follower. Runs to the original end time,
compares every saved qpos sample, and records first nonfoot support and final contacts.
It does not modify/dispatch the shared worker or change its collision policy.

Added tests/test_terrain_contact_analysis.py: unnamed-geom identity, source preservation,
output reuse refusal. Full regression command (from scene2test):

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_terrain_contact_analysis.py tests/test_terrain_courses.py tests/client tests/server tests/test_procedural_world.py tests/test_scene_search.py tests/test_scene_search_runner.py -q
```

**123 passed, 1 existing Starlette/httpx warning, 78.59 s.** Targeted tests: 27 passed.
Ruff check on both new tools and test passed after import sorting/formatting.

Attempt to add contact IDs/body names directly to terrain_worker.py failed during
apply_patch Update File's read phase with the same bwrap namespace error. No replacement
write path was used. Production contacts.jsonl logging is therefore NOT yet upgraded.
Saved a seven-field minimal patch at .workhistory/terrain_contact_logging.pending.patch.
`git apply --check .workhistory/terrain_contact_logging.pending.patch` passed (read-only).
The user can apply this locally; do not claim that generating/checking the patch applied it.

## Evidence and paths

Original jobs remain under:
`/workspace/g1_failure/runtime/terrain_validation/20260912T155805_545977Z/`

- ramp: job_ee50b46e64074284b6888a69e977b6af
- stairs: job_0f35f06be6514f58927e5bb51b3e84a6

Sampled contact reconstruction:
`/workspace/g1_failure/runtime/terrain_diagnostics/20260912T162613_691599Z/`

Independent CUDA replay (diagnostic.json per original job):
`/workspace/g1_failure/runtime/terrain_diagnostics/20260912T162854_803277Z/`

Commands, with JOB_RAMP/JOB_STAIRS denoting the above full original paths:

```bash
PYTHONPATH=src .venv/bin/python tools/analyze_terrain_contacts.py JOB_RAMP JOB_STAIRS
SIM_SERVER_ONNX_PROVIDER=cuda PYTHONPATH=src .venv/bin/python tools/replay_terrain_diagnostic.py JOB_RAMP JOB_STAIRS
```

Both replays used CUDAExecutionProvider / MuJoCo 3.12.0. Sample comparisons: ramp
689/689, stairs 182/182, maximum absolute qpos difference **0.0 for both**. This is
strong same-episode reproduction evidence, not a guarantee for arbitrary machines or
versions. Input/script hashes are in reports; cosmetic formatting/import sorting took
place after the first execution, so saved script hashes refer to the executed versions.
These diagnostic scripts do not replace the full rollout/provenance runner.

Original video frames at nominal 25 s (ramp) and 8.5 s (stairs) were extracted to
/tmp/terrain_ramp_diagnostic_20260912.png and /tmp/terrain_stairs_diagnostic_20260912.png
and viewed. They show an upright robot near the terrain transitions; the overhead
view alone cannot resolve a millimeter-scale ankle contact. No original video changed.

## Ramp: observations versus inference

- Original/replay end time 34.42 s, STUCK; no nonfoot support collision in replay.
- Ramp begins x=3.8 m; base remains approximately x=3.766 m.
- Last 10 s commanded forward speed spans 0.2498288–0.2499999 m/s. The base x range
  is 3.7599267–3.7682955 m (8.37 mm); it oscillates without meaningful progress.
- Sampled late contacts are ankle_roll bodies touching entry flat and ramp surfaces.
  Absolute normal z is 1.0 on the flat, 0.9961947 (cos 5 degrees) on the ramp.
  No unexpected vertical-wall normal was found among those sampled contacts.
- Terminal replay contacts explicitly show rear/right foot contacts on flat and front
  contacts on slope. No evidence that follower's safety guard was commanding a stop.

Inference: the closed-loop gait/controller/terrain interaction stalls at the slope
transition. The existing policy adapter observes proprioception/commands, not a terrain
height map or footstep targets. A terrain-adaptation limitation is plausible, but these
runs do NOT isolate policy training, gains, friction, seam contact, or robot morphology
as the sole cause. A matched zero-slope/slope/transition experiment is still needed for
that causal claim. Do not weaken the stuck test or call every generated path traversable.

## Stairs: identified termination cause

At 9.065 s the replay reproduced the original logged contact positions and distances:

- terrain geom 23, world_surface_2 (second step top, approximately z=0.08 m);
- robot geom 57 (unnamed), body 12, **right_ankle_pitch_link**;
- first contact position [4.400042468, 7.765891683, 0.078911765] m;
- penetration 0.00216947 m (about 2.17 mm); three contact points logged;
- normal is mostly upward; no fall required for COLLISION termination.

TerrainMetrics permits support contact only on ankle_roll bodies (foot contact geoms).
The right_ankle_pitch_link is outside that set, so the nonfoot collision rule correctly
explains the termination. This is not a generic fallen-robot result or an unidentified
phantom collision. Whether ankle housing contact should be allowed is an experimental
policy choice, NOT grounds to silently relax the current oracle to make the run pass.
Current evidence establishes contact with the configured collision model, not a claim
about real hardware contact fidelity.

## Next work and unchanged boundaries

Apply the saved worker logging patch locally to complete production provenance.
Then run matched terrain-transition controls (zero/positive slope, gentle transition,
small stair heights) under a frozen controller/evaluator, recording failures unchanged.
No terrain AFS comparison, policy retraining, controller retuning or server terrain
integration was done. No services were restarted. All initial failures are preserved.
