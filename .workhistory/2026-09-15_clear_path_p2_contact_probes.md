# 2026-09-15 — P2 CUDA arm and real-contact pushing probes

## Request and scope

User requested starting the next work after P0/P1 clear-path fixture/audit.
Implemented isolated real-physics unit probes, not complete obstacle clearing.
No paid API, robot-side GPT, AFS change, server registration, hardware command,
git commit/push or original GR00T source modification was performed.
Existing worktree was clean before this turn. All changes are additive files.

## Implementation

- `scene2test/src/clear_path/push_probe.py`: CUDA gait plus scratch-state palm IK,
  upper-body rate-limited targets and actuator torque control; named joint indexing
  preserves the appended free box state. Numerical/contact/fall guards and logs.
- `scene2test/tools/run_clear_path_probe.py`: independent bounded runner, exact
  scene/audit/protocol/result/manifest, real MP4/GIF and HTML report.
- `scene2test/tools/render_clear_path_probe.py`: overhead recorded-state replay,
  no physics stepping; source SHA256 provenance; refuses output overwrite.
- `scene2test/tests/test_clear_path_probe.py`: live-state immutability during IK,
  target rate bounds, missing-side and nonfinite-input rejection.
- `scene2test/docs/CLEAR_PATH_P2_PROBES.md`: usage, contract, limits and evidence.

## Trial ledger (all retained under runtime/clear_path_probes)

1. `20260915T152302_601258Z`: arm v1, 8 s, CUDA, FAIL, final palm error
   0.122404 m. Base drifted back ~0.15 m. Upper PD 60/3; no base hold.
2. `20260915T152816_231330Z`: arm v2, 8 s, CUDA, PASS, final error
   0.0447265 m. Added GT base hold and upper PD 80/4 plus bias compensation.
   Also forward-updated live derived state after stepping for measurements.
3. `20260915T152925_963414Z`: push v2, 11 s, CUDA, FAIL; zero hand contact,
   no meaningful box translation. Initialized x=3.03, palm offset
   [0.44, +/-0.20, -0.15], forward command 0.06 m/s. Recorded geometry showed
   palms above/short of box. Offline scratch IK at recorded t~6 s yielded
   residuals 0.208/0.212 m for old target, versus 0.016/0.018 m for
   [0.26, +/-0.20, -0.05]. This is kinematic diagnosis, not new execution.
4. `20260915T153547_949359Z`: push v3, 11 s, CUDA, FAIL; x displacement
   0.0126676 m, y -0.0025208 m; 395 hand-contact steps; peak per-contact
   normal force 17.0799 N; final palm error 0.0210048 m. Initial x=3.2,
   reachable target, forward command 0.10 m/s. Camera raised to -60 degrees.
5. `20260915T153729_086686Z`: push v4, 11 s, CUDA, FAIL; x displacement
   0.0315623 m, y -0.0082936 m; 618 hand-contact steps; peak per-contact
   normal force 21.3346 N; final palm error 0.0228573 m. Only forward command
   increased to 0.18 m/s. Force guard and >0.08 m success threshold unchanged.

All trials: valid execution, duration reached, no detected fall or forbidden
robot/world contact. Self-collision classification is not implemented. Settling
box z displacement ~-0.000057 m is not manipulation progress. Counts are physics
steps with contact, not distinct pushes. Tuning trials are not a success-rate study.
Every result keeps clear_path_success=null. No side-bay clearing was attempted.

## Visual evidence

Original first-camera videos were partly wall-occluded. Kept them unchanged and
rendered second arm trial recorded states into its `overhead_replay/` directory.
v3/v4 actual rollout camera uses distance 3.8, azimuth 120, elevation -60.
Visually inspected v3 final PNG: robot and box are visible from above.
MP4/GIF are physics-derived robot states, not object-position illustrations.

## Validation and environment

- `pytest tests/test_clear_path_probe.py tests/test_clear_path.py
  tests/server/test_terrain_guards.py -q`: 19 passed (27.23 s final rerun).
- Ruff check on the four added Python files: passed.
- Local MuJoCo + existing Walk.onnx used CUDAExecutionProvider in every probe.
- Sandbox default shell still fails bwrap; approved escalated execution used for
  scoped reads/tests/runtime. Update-file patch helper remains unavailable; added
  files were revised through Add File while still untracked and owned by this turn.
- First trial source was Ruff-formatted after startup hash capture; no controller
  semantics changed. Subsequent controller revisions are captured by per-run hashes.

## Remaining work

P2 remains partial, not done. Arm reaching and real hand contact were demonstrated,
but displacement remains below threshold. Next implement contact-maintaining
push/retract control and validate repetitions before side-bay clearing/traversal.
Do not describe GPT as providing a manipulation skill: planner integration waits
for a validated executable skill. Preserve these negative results in later reports.
