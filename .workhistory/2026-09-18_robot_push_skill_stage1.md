# Robot push skill — first implementation/physical validation stage

## Request and scope

User approved expanding robot execution skills, starting with pushing before grasp/carry
and jumping. The robot must decide strategy; the evaluator must not prescribe the solution.
Implemented a bounded reusable near-contact primitive and tested actual CUDA physics.
This stage does NOT connect/advertise the primitive in the live GPT goal-agent yet.
No API calls or changes to legacy robot/server/AFS/controller assets.

Initial worktree was clean. Added files only: robot_vlm/push_skill.py,
robot_vlm/push_validation.py, tools/run_robot_push_validation.py,
tests/test_robot_push_skill.py, docs/ROBOT_PUSH_SKILL.md and this record.

## Design

Reuses existing contact supervisor and ArmGaitController (scratch IK + upper-joint
actuator targets + CUDA Walk.onnx gait). PushSession takes measured object/base poses
and caller-selected world XY target. Preconditions reject unsupported approach/heading,
shape, height or displacement. Frame transforms remove the global +X assumption from
the session; rotation equivariance is unit-tested, not physically generalized evidence.
Supported fixture geometry remains 0.8x1.1x0.7 m and short forward-aligned pushes.

ContactControl's retraction trigger is shifted to the requested displacement rather
than hard-coded 12cm. Success requires <=2cm final XY target error, real push contact,
>=0.5sec continuous release, sufficient run duration and valid/allowed dynamics.
The validation runner binds the selected clear_box and enforces hand/object contact
allowlisting, 120N per-contact force bound, fall/numerical guards and no injected forces.
Self-collision classification remains unimplemented.

No runtime qpos teleport, forced object displacement or fake attachment. Initialization
places the robot at x=3.2 before stepping: explicit near-box unit-test setup. Not autonomous
approach, side-bay clearance or original-spawn navigation evidence. A green legacy bay
marker visible in the video is NOT the short-push unit-test target.

## Physical evidence

Root `/workspace/g1_failure/runtime/robot_push_validation/`:

| Run | Condition | Requested / achieved forward displacement | XY target error | Result |
| --- | --- | --- | --- | --- |
| 20260918T165734_539321Z | 2kg, friction .5, y=0 | 8cm / 8.0504cm | 5.80mm | success |
| 20260918T165836_658666Z | 2kg, friction .5, y=.02m | 8cm / 8.0414cm | 9.03mm | success |
| 20260918T165908_033391Z | 8kg, friction 1.2, y=0 | 8cm / .7542cm | 72.46mm | failure |

All CUDAExecutionProvider, 18s, valid physics, no fall/forbidden contact, hands released.
Peak per-contact forces: 30.90N, 21.61N, 22.45N. The hard condition is an honest target
failure, not an infrastructure error. These three selected conditions are not a success
rate estimate or proof of general manipulation; mass/friction were changed together.

Each run retains report.html, MP4/GIF/final frame, state/control/contact traces, result,
audit/source/asset hashes, protocol and manifest. All 10 listed artifacts per run pass
SHA256 verification; each MP4 first frame decodes. First run's final image visually
inspected: standing robot and box, released-hold phase. No old evidence overwritten.

## Tests and next gate

89 passed, 2 GPU-specific tests skipped in 10.10s across push skill, existing clear-path,
goal/VLM, diagnostic and API failure regression tests. Actual new push GPU runs above
were executed separately. Ruff passes for all four new Python files.

Next: versioned opt-in typed push action and capability description, controller handoff,
original-spawn approach chosen by GPT, designated contact exceptions only during push,
post-push geometry feedback and replanning. Do not label unrestricted push/manipulation
available until integration is physically validated. Grasp/carry requires a supported
manipulation policy and appropriate hand actuation (current asset has fixed finger meshes);
jump requires a separate demonstrated executor. Current live goal-agent remains unchanged.
