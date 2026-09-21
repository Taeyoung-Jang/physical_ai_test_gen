# Clear-path P0/P1 prototype

2026-09-15. Independent prototype under `src/clear_path`. Existing G1 workers,
navigation/terrain bundles, AFS contracts and legacy Panda code are unchanged.
This is environment preparation and a static compatibility audit, NOT a robot push
executor, GPT robot policy, or demonstrated manipulation success.

## Run and inspect

From `scene2test`:

```bash
MUJOCO_GL=egl uv run python tools/setup_clear_path.py
```

Requires existing local GR00T assets, MuJoCo and imageio/ffmpeg. No new model download,
API key, API request or policy inference is needed. `--groot-root` overrides asset root.
`--no-render` omits 3D/media rendering but still exports the map and report.
Outputs are exclusive timestamp directories below `/workspace/g1_failure/runtime/clear_path`.
Open **report.html** with its sibling files intact; it explains the initial state and
links previews, maps, robot audit and artifact manifest.

`scene_preview.mp4` and `scene_preview.gif` are a camera orbit around a static initial
scene, explicitly labeled **NOT a rollout**. Physics time stays zero; the G1 does not
walk or push. `robot_view.png` comes from an added simulation camera attached to the
torso, not a calibrated physical sensor. The initial camera pose, field of view and
image dimensions are recorded in `initial_state.json`.

## Fixed first environment

- Corridor x=0..8m, y=-0.8..0.8m; side bay x=3.3..4.7m, y=0.8..2.5m.
- G1 start (1,0), destination (7,0), both world meters.
- Box center (4,0), full size 0.8×1.1×0.7m, mass 2kg, sliding friction 0.5.
- Hypothetical box destination (4,1.65), floor sliding friction 0.8.
- Navigation uses a 5cm grid with 0.35m circular footprint plus 0.05m clearance.
  These are planning assumptions, not a verified whole-body footprint.

The initial map has no path. A separately labeled hypothetical map places the box at
its destination and finds a reference path. No simulation state is moved to create that
comparison image. It is not a measured after-state or a manipulation-feasibility proof.
Topology/dimensions are deliberately fixed in this initial fixture; this is not yet an
AFS parameterized manipulation domain.

SceneGraph uses the repository's existing SceneGraph serialization with explicit world-m
frame metadata and stable IDs matching MuJoCo geoms/bodies/sites. Graph metadata marks
state_version=0. Only the initial runtime state is exported; continuous graph/map updates
belong to the later action runner. Bounding floor surface is not free navigation space.

The box has a freejoint and physically derived inertia. Object-only tests show floor
support and response to initial velocity. Those tests do not constitute robot interaction.

## P0 findings and integration decision

The actual G1 asset has 29 actuators, including seven joints per arm. Both palm meshes
have collision geoms. Finger meshes are fixed; active finger joints are absent. A small
nonphysical site at each palm's source-model offset supports future kinematic targeting.
Initial-pose arm position Jacobian rank is three; this says nothing about reaching a
particular contact, applying adequate force, or remaining balanced during a push.

Appending the box adds 7 qpos and 6 dofs: (36,35) → (43,41). Existing robot actuator
order, joint state addresses and limits are checked for equality, and the 86-value
legacy gait observation is identical at the tested pose. ONNX metadata inspected locally
shows 516 input values and 15 outputs; no inference was performed for this milestone.
The existing controller holds the other 14 joints at zero with PD, so it must NOT be
described as already supporting palm-target execution.

Candidate P2 path: a separate upper-body target/IK adapter over the existing gait, with
measured contact and stability guards. Local decoupled WBC is an alternative to evaluate
if this approach fails. No automatic package installation or original-controller replacement.
Stable pushing and the feasibility of this particular side-bay maneuver are still open.

## Contracts and evidence boundary

`clear_path@0.1` is a new task designation, not an advertised common-server capability.
The action schema describes navigate_to/push_object/observe/stop with world targets and
state_version. Guard checks reject stale states, unknown objects, basic envelope violations
and unimplemented actions. Enabled actions default to empty. An envelope check is NOT
a collision/reachability check, and no action is executed by this package.

The elementary evaluator consumes measured booleans: valid, goal_reached, path_open,
fallen and forbidden_contact. Invalid execution returns INDETERMINATE, not robot failure.
The future runner still needs contact classification by body pair and action phase,
timeouts, observation updates and integration with actual measurements.

Robot XML/meshes/YAML/policy hashes, module/CLI hashes, model version and individual
artifact sizes/hashes are exported. scene.xml references the original external mesh
directory, so it is not a self-contained portable robot asset package. Failed rendering
runs preserve map/report/diagnostics and exit nonzero; never substitute a blank video.

## Verification and remaining work

Tests exercise initial/hypothetical connectivity, SceneGraph roundtrip, shared geometry,
physical box mass/friction/support/motion, rejected configs/actions, verdict separation,
and actual G1 named-joint/palm/observation compatibility (asset test skips when absent).

```bash
uv run python -m pytest tests/test_clear_path.py tests/server/test_terrain_guards.py tests/test_terrain_courses.py tests/test_procedural_world.py -q
```

Remaining P0/P1 integration items are a proven upper-body control adapter, continuously
measured state updates and action-phase contact evaluation. Next P2 milestone is a real
scripted push and passage recorded in a distinct rollout video, including failures.
GPT calls, VLM observation, adaptive manipulation AFS and fair campaign budgets come later.

See [full plan](GPT6_ROBOT_CLEAR_PATH_PLAN.md). MuJoCo named state access and rendering
reference: https://mujoco.readthedocs.io/en/stable/python.html.
