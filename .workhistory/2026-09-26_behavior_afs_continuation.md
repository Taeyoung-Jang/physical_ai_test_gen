# Behavior-conditioned AFS continuation — 2026-09-26 UTC

## User direction

Inspect prior robot behavior and select informative next environments. Do not
continue making the same failure more severe (e.g. increasing box mass forever).
Probe easier conditions, estimate boundaries, and explore alternative mechanisms.
Do not instruct or modify robot strategy to manufacture a failure.

## Resumed state

On resumption, commit `151c122` already contained behavior.py, run_behavior_afs.py,
scene_config.py, its runner/CLI connection, and core tests. Preserved those changes.
Completed the pending docs and CLI/physics-parameter tests, and recorded source
hashes for scene_config and fixture contracts in robot protocol. The robot's
policy, gait, push controller, safety limits and success thresholds are unchanged.

## Implemented scope

- Verified prior-run manifest and required artifacts, extracted actual XML mass
  and friction, action sequence, skill feedback and phase-specific sampled base tilt/height.
- LLM request uses evidence IDs, alternative explanations and falsification criteria.
  Host requires two distinct axes and ranges on both sides of the current setting.
- One original control repeat, two boundary probes, two alternative-axis probes,
  two independent full-domain exploration points; not all candidates must execute.
- Comparable opposite whole-task labels differing on one scene axis produce a
  provisional bracket midpoint. No monotonicity/causal/statistical certainty claim.
- Explicit history-based duplicates and axis cooldown; duplicates are not silently
  resampled. History must be supplied, not an implicit persistent memory service.
- Only box mass, box friction and global floor friction are currently connected
  to this VLM robot backend. Planner footprint/task/robot changes are rejected.
- The default and offline paths never call the API or launch a robot. `--live`
  calls the AFS model once and generates configurations; robot execution is separate.

## Evidence and validation

Prior run: `/workspace/g1_failure/runtime/robot_goal_agent/20260921T155205_243359Z`.
During the prior implementation, sampled push-phase maximum tilt was 8.3038 degrees
and minimum base height 0.73018 m. These do not establish imminent loss of balance.
One camera frame was inspected; the automatic AFS input remains logs, not video.
Prior run physically pushed twice but did not reach the goal before its call budget.
No evidence establishes that mass was the cause; no measured success boundary yet.

Resumed offline compilation:
`/workspace/g1_failure/runtime/behavior_afs/20260926T023733_057915Z`
`ready=7`, `origin=offline_fixture`: pipeline validation, NOT LLM-selected failures.
Previous offline compilation is retained at
`/workspace/g1_failure/runtime/behavior_afs/20260921T162724_481787Z`.

Relevant CPU regression: 123 passed, 5 skipped, 15.70s. Includes evidence tampering,
path escape, invalid anchors, diversity/range/evidence-ID rejection, brackets,
dedup/cooldown, no-network default with a dummy key, and MuJoCo model compilation
confirming mass/friction settings reach the physical model. No GPU rollout ran.
Ruff checks and formatting completed. API key presence checked as a boolean only;
no credentials were printed. See turn result for availability.

## Remaining boundaries

- No live AFS model or new robot outcome validated in this continuation.
- No autonomous multi-round campaign, valid-rollout budget comparison, or repeated
  stochastic boundary estimation yet. Tests of bracket logic are synthetic.
- Whole-task boundary is not a fixed action skill boundary: GPT may choose different actions.
- Geometry/urgency/turn/obstacle and local-friction perturbations are not added to
  this backend; do not advertise them as executable merely because terrain supports geometry.
- Contact coefficient combination can mask an individual coefficient change.
- New runner source hashes require a fresh same-code control before boundary
  comparisons with new runs; past mismatched protocols remain hypothesis evidence only.
- OpenAI Docs Structured Outputs guidance informed schema/host validation; reused
  existing Responses provider, retained model name and no retry behavior.

Documentation: `scene2test/docs/BEHAVIOR_AFS.md`.
