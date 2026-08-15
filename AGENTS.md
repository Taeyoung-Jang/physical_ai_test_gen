# Scene2Test workspace memory

Last refreshed: 2026-07-13 (Asia/Seoul).

## What this repository is

This workspace contains one Python project, `scene2test`, for automated regression and
failure-condition discovery for robot pick-and-place behavior. It represents workspaces as a
shared 3D `SceneGraph`, perturbs or augments scenes, runs a Franka Panda in PyBullet, evaluates
continuous safety/robustness margins, and records counterexamples and reports.

The project has two related pipelines:

1. The original Scene2Test Active Failure Search (AFS) pipeline searches an 8-dimensional scene
   mutation space with a learned surrogate and an acquisition function.
2. The v2 LAM-Guided pipeline observes a replaceable action policy, profiles its behavioral
   weaknesses, generates policy-conditioned 3D failure cases, reruns the policy, and refines
   PASS/FAIL boundaries.

This is a simulation/research prototype. It does not control real robot hardware, train a VLA,
or perform dynamic grasp/contact validation in its main oracle.

## Repository map and source of truth

- `README.md`: best high-level overview of both pipelines.
- `.blueprint/00_blueprint.md`: original problem statement and AFS design intent.
- `.blueprint/01_blueprint.md`: LAM-Guided extension design intent.
- `scene2test/`: executable project; run commands from this directory.
- `scene2test/src/`: implementation. Prefer code and tests over stale prose when they disagree.
- `scene2test/config/`: robot, task, oracle, scene generation, and LAM-guided settings.
- `scene2test/tests/test_p1_*.py` through `test_p13_*.py`: phase completion scripts. Many are
  executable `main()` scripts rather than pytest-discovered tests.
- `scene2test/docs/GAP_ANALYSIS.md`: most useful implementation-vs-blueprint audit, but it was an
  untracked work-in-progress when this memory was written.
- `scene2test/PLAN.md`: P0-P10 implementation history; `EXECUTION.md` and
  `LAM_GUIDED_WORKFLOW.md` document v2 usage.
- `scene2test/data/` and `scene2test/reports/`: scenes, run logs, generated meshes, GIFs, and
  derived reports. Treat most timestamped outputs as generated artifacts, not hand-authored code.

There was no pre-existing `AGENTS.md`. `CLAUDE.md` was empty at the time of inspection.

## Original AFS pipeline

The central contract is `src/scene_graph.py`: every procedural or RGB-D source should emit the
same `SceneGraph` containing support surfaces, objects/roles, relations, unknown regions, and
metadata. Downstream code is intended to be source-agnostic.

The implemented flow is:

`SceneGraph -> 8D mutation sampling -> 16D feature vector -> PyBullet kinematic check -> six-margin Physical Oracle -> surrogate training -> acquisition/top-K diversity -> repeat -> logs/reports`

Important implementation facts:

- Mutation dimensions: `target_dx`, `target_dy`, `obstacle_angle`,
  `obstacle_dist_to_target`, `human_zone_x`, `human_zone_y`, `tray_occupied`, and
  `occlusion_ratio`.
- The feature vector is actually 16D: eight scene features plus the normalized eight mutation
  parameters. Ignore the stale 39D statement in `scene2test/README.md`.
- `RFSurrogate` (ExtraTrees regressors, one per output) is the default; `GPSurrogate` is the
  comparison implementation. They predict six margins, not a direct PASS/FAIL label.
- The six margin keys are `reach`, `clearance`, `collision`, `safety`, `goal`, and `perception`.
  Robustness is their minimum. Verdict priority is safety `BLOCKED`, then `FAIL` for robustness
  <= 0, `WARN` within `decision.warn_band`, otherwise `PASS`.
- AFS cold-start uses LHS/boundary seeds until `min_train_size` (default 15), then scores a
  candidate pool (default 1000) using failure probability, uncertainty, safety priority,
  novelty/redundancy, coverage, and diverse top-K selection.
- Modes are `cold`, `warm`, `random`, and CLI-level `compare`. Warm mode reuses a cross-scene
  surrogate from `scene_library.py`.
- The main simulator/oracle is deterministic and kinematic (IK and geometry queries). The
  animation tool has a separate `--physics` mode for visual observation, but that does not make
  the main search oracle dynamics-aware.

## LAM-Guided v2 pipeline

The implementation is mostly isolated under `src/lam_guided/` and is gated by
`lam_guided_failure.enabled` or CLI `--enabled`, preserving the original AFS path.

The conceptual loop is:

`observe policy -> encode behavior -> profile vulnerability -> generate/filter failure candidates -> execute -> Policy + Physical Oracles -> FailureMemory -> boundary refinement/reporting`

Important implementation facts:

- `src/policies.py` provides the `ActionModel` protocol, deterministic `RuleLAMProxy` baseline,
  and noisy heuristic `MiniActionModel`. The mini model is not a neural LAM/VLA.
- Current behavior representation has 8 features and the vulnerability profile has 7 axes.
- Implemented failure families are `semantic_distractor`, `occluder`, `path_blocker`, and
  `human_safety_intrusion`.
- `PolicyOracle` detects policy-level failures such as wrong-object grounding/picking, safety
  noncompliance, instability, and recovery failure. A separate physical check evaluates margins.
- `GeneratedAssetBank` supports procedural assets and offline mesh assets. `asset_gen.py` can use
  Shap-E optionally and falls back to procedural defaults when unavailable.
- Boundary refinement currently targets semantic-distractor distance and path-blocker offset.
- `src/policies_vla.py` plus `src/lam_guided/closed_loop.py` define an RGB closed-loop policy path,
  a GPU-free `StubReachPolicy`, and a lazy-loading `OpenVLAPolicy` wrapper. The wrapper existing
  is not evidence that the real OpenVLA-7B model has completed an end-to-end run.
- Current LAM-guided candidate selection is independent of original AFS. In the actual loop it
  assigns `family_prior + coverage` scores and then performs family-stratified selection. An
  `_score_candidate` helper mentions novelty/redundancy but is not used by `run()`.

## Known gaps and claim boundaries

Do not describe the following as complete without new evidence:

- Track B is not a production RGB-D perception pipeline. The GT path copies supplied object
  poses; the mask path has a known pixel-to-valid-point indexing bug; object detection,
  segmentation, role inference, semantic extraction, and AFS/LAM end-to-end wiring are absent.
- LAM-Guided candidates are not merged into the original AFS pool, and guided scoring does not
  reuse the AFS surrogate or uncertainty.
- Blueprint families 5/6 (`destination_confusion`/occupied and grasp-difficult objects) are not
  implemented.
- Action subgoals are produced but not sequentially executed as reach/grasp/place/release; the
  open-loop rollout is effectively a selected-object IK reach, so full place/release success is
  not validated.
- The LAM-Guided A/B/C comparison needed to quantify guided gain has not been implemented.
- OpenVLA-7B real-model E2E validation, rendering-domain-gap mitigation, and Franka/WidowX
  embodiment calibration remain open.
- Reported experiment numbers in markdown are prototype results, not a substitute for rerunning
  the relevant command with a recorded environment and seed.

The priority backlog captured in `docs/GAP_ANALYSIS.md` is: first quantify LAM-guided gain, make
the pixel-to-SceneGraph path genuine at least with PyBullet segmentation, and run real OpenVLA;
then add missing families/full subgoal execution/occlusion boundaries; finally merge AFS and
guided search and expand features.

## Environment and commands

- Package metadata requires Python `>=3.11`; Ruff targets Python 3.12. Root documentation says
  Python 3.11 while `scene2test/README.md` says 3.12+, so treat `pyproject.toml` as authoritative.
- Dependency manager: `uv`. A project-local `.venv` existed during inspection.
- Apple Silicon uses `pybullet-arm64`. Prefer headless runs with `PYBULLET_MODE=DIRECT`; macOS
  PyBullet GUI rendering is unreliable. GIF/video output additionally needs ffmpeg.
- Core install: `cd scene2test && uv sync`; optional extras are `--extra vla` and `--extra gen3d`.
- Generate scenes: `uv run python src/scene_generator.py --n 20 --output-dir data/scene_library --seed 0`.
- Run AFS: `PYBULLET_MODE=DIRECT uv run python src/active_failure_search.py --scene data/scene_library/scene_00001.json --mode cold --rounds 5 --tests-per-round 20`.
- Run LAM-guided: `PYBULLET_MODE=DIRECT uv run python src/lam_guided/lam_guided_loop.py --scene data/scene_library/scene_00001.json --action-model mini --rounds 4 --batch-size 8 --enabled`.
- Dashboard: `uv run streamlit run app.py`.
- Broad pytest command: `PYBULLET_MODE=DIRECT uv run pytest tests/ -v`, but also run the phase
  scripts directly when validating P1-P13 because pytest does not discover all `main()` checks.
- Running integration scripts writes timestamped logs and reports. For read-only exploration or
  review, do not run them unless those workspace mutations are acceptable.

## Working-tree caution and active direction

Always inspect `git status` before editing and preserve user changes and generated evidence.
When this memory was written, `main` matched `origin/main` but the worktree was dirty with
user-owned LAM/VLA integration work plus new logs and `docs/GAP_ANALYSIS.md`. The code changes
were separating LAM selection from VLA execution in `RolloutTrace`/`PolicyOracle`, adding a
`lam_vla` execution mode to `lam_guided_loop.py`, and changing OpenVLA Apple Silicon handling to
MPS float32 with float64-buffer patching. Do not revert or overwrite that work.

Refresh this memory when architecture, validated capabilities, or the gap backlog materially
changes; avoid recording transient run IDs or machine-specific generated paths here.
