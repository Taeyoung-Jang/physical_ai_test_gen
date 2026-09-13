# Configurable terrain scenes (implementation in progress)

This adds a separate static 2.5D course generator and isolated GPU runner. It does not
establish that the G1 gait can traverse every generated scene. The legacy server's
navigation worker is unchanged and **must not be used for terrain bundles**. Server
registration guards/integration are pending permission; do not register these bundles
with `simulation_server.worlds` or submit them to navigation@1.0 on the shared server.

## Set up scenes

From `scene2test`:

```bash
# Eight starter courses, with graph/map/XML/top-view/height-friction plot/3D rendering:
MUJOCO_GL=egl PYTHONPATH=src .venv/bin/python tools/setup_terrain_scenes.py --preset all --render

# A composed recipe with sampled slope, stair height, friction, gap and roughness:
MUJOCO_GL=egl PYTHONPATH=src .venv/bin/python tools/setup_terrain_scenes.py \
  --config config/terrain_course.yaml --n 8 --sampler sobol --seed 42 --render
```

Use `--sampler random` for independent uniform samples. Sobol samples the configuration
parameters, not the robot's actions. Invalid geometry/path candidates are recorded in
`suite.json`, not silently replaced and not counted as robot failures. CLI seed controls
both parameter sampling and per-scene obstacle/roughness randomization. Same recipe,
seed and generator version reproduce the scene revision. Keep these fixed for comparisons.

Defaults write to `/workspace/g1_failure/runtime/terrain_scenes/<timestamp>/` without
overwriting existing evidence. A ready entry contains its bundle path and scene revision;
`recipe.yaml` records resolved settings. `--output-root` changes the parent directory.

## Available sections

Every course has a flat entry and exit. List sections in `course.segments` to compose them.
All distances are meters; angles are degrees. Unknown keys are rejected.

| Kind | Parameters | Meaning |
|---|---|---|
| `flat` | `length_m`, `width_m`, `friction` | Flat corridor, including narrower sections |
| `ramp` | `angle_deg`, `length_m`, `landing_m` | Uphill, flat landing, downhill; length is each ramp's horizontal run |
| `stairs` | `step_height_m`, `tread_m`, `count`, `landing_m` | Ascending stairs, landing and descent |
| `friction` | `length_m`, `friction` | Low/high-friction flat segment |
| `rough` | `length_m`, `amplitude_m`, `cell_length_m` | Seeded continuous piecewise-linear uneven ground along travel direction |
| `obstacles` | `length_m`, `count`, `size_min_m`, `size_max_m`, `pattern` | Axis-aligned boxes with independent length/width/height sampling; `random` or `slalom` placement |
| `bottleneck` | `length_m`, `gap_m` | Two barriers with a central opening |

Global `width_m` is 1.2–8 m and section width cannot exceed it. Friction is .01–2.
Ramp angle is 0–30 degrees; stair height .01–.3 m, tread .25–1.5 m, count 1–12.
Roughness amplitude is 0–.2 m. Obstacle dimensions are .1–2 m, count 0–30 per section.
Additional constraints apply: maximum terrain height 2 m, at most 12 sections, existing
map-size limits, nonoverlapping geometry and reachable planned route. These numeric input
limits bound generation, not robot capability. A valid numeric setting can still be rejected
if too narrow, overlapping or outside configured planning limits.

Presets: `flat`, `ramp`, `stairs`, `low_friction`, `rough`, `slalom`, `bottleneck`, `mixed`.
The existing random maze/room generator remains available separately; this version does
not automatically place ramps and stairs throughout arbitrary branching mazes.

## Representation and physics

- `TerrainSpec` extends the existing spec without adding fields to legacy flat specs.
  Legacy scene IDs/revisions remain unchanged.
- Analytic rectangular support surfaces define height, slope, bounds, friction and category.
  Their same corners generate convex MuJoCo meshes. Obstacles and walls remain static boxes.
- Graph nodes with role `traversable_surface` contain the plane equation and collision ID;
  adjacency relations connect neighboring supports. They are not ordinary obstacle nodes.
  The legacy `floor` graph entry is visual backing, not the terrain's traversable surface.
- `navigation_map.json` includes height, slope, friction grids and XYZ reference samples.
  XY obstacle inflation remains circular. Edges reject unsupported segments, excessive
  slope and support-boundary jumps above configured limits. Path simplification checks
  the same terrain transitions.
- `planning_max_slope_deg` (25) and `planning_max_step_m` (.22) are experimental planning
  assumptions. They do not encode learned G1 limits or guarantee full-body/footstep safety.
- The backing floor is noncolliding; only terrain surfaces support the robot. Terrain
  contact priority selects the configured sliding friction even when robot geom friction
  is larger. This avoids silently retaining high friction in a nominal slippery segment.

No dynamic obstacles, deformable ground, holes, overhangs, bridge layers, arbitrary object
meshes, cross-slope navigation or learned footstep planner are provided in this version.

## Isolated GPU validation

```bash
PYTHONPATH=src .venv/bin/python tools/run_terrain_validation.py \
  --suite /workspace/g1_failure/runtime/terrain_scenes/RUN/suite.json \
  --names flat ramp stairs low_friction --duration 120 --speed 0.25
```

The runner uses a separate subprocess per episode, bounded wall time and CUDA provider
verification. It does not use the existing server job queue or restart its services.
Outputs default to `/workspace/g1_failure/runtime/terrain_validation/<timestamp>/`:
request/result, graph/map/XML, state/action/contact logs, reproduction metadata, MP4, GIF,
thumbnail and trajectory PNG. Artifact hashes and sizes are checked after execution.

The terrain-only evaluator uses body height **relative to local ground**, distinguishes
foot/support contacts from non-foot collisions, and measures tangential ankle/support slip
on mesh surfaces. No foot-contact samples means unknown slip, not measured zero slip.
The gait and waypoint controller remain ground-truth-based; they do not perceive terrain
or plan individual footsteps. Goal, fall, collision, stuck and timeout remain separate.
Numerical/worker errors are not evidence of a robot task failure.

`procedural_world.terrain_presets.apply_parameters` applies strict dot-path parameters to
recipes, and `generate_course` builds candidates. These are reusable AFS scene-building
interfaces, but the previous 2D obstacle AFS pilot does not automatically search every new
terrain parameter and no terrain AFS superiority comparison has been run.
