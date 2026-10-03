# Goal outcome AFS redesign — 2026-09-26 UTC

User clarified that failure means the evaluated robot system cannot achieve its
initial goal by any method available to that system; asked for a new design.

Reviewed blueprint, project roadmap/audit, behavior AFS, goal-agent/push/budget
docs and the actual runner's termination logic. Preserved unrelated in-progress
context-binding fix and previous experimental evidence.

Created `scene2test/docs/GOAL_OUTCOME_AFS_DESIGN.md` as a design specification,
explicitly distinguished from the still-current implementation.

Decisions:
- Task-goal oracle is primary; contacts, falls and local skill errors are measured
  events and may be followed by recovery/another strategy. Avoid evaluator-imposed
  contact stopping in the goal-only profile. Keep native robot behavior explicit.
- Declare fixed robot/task/budget conditions. Keep current example 10 policy calls
  and unlimited simulation-time default; no automatic restoration of a120s limit.
- PASS for measured goal, FAIL for valid budget/robot-declared completion without
  goal, INCONCLUSIVE for bench interruption/invalid execution, NOT_RUN for invalid
  scene. Do not infer the missing continuation of historical guarded runs.
- Separate task termination, execution validity and event telemetry. Record forces
  even for unexpected contact; remove misleading fixed Mock reporting text in a
  future implementation step.
- AFS tests success-side recovery, empirical boundary brackets, alternative causes,
  interactions, new regions and reproducibility. Replace the v1 compulsory
  straddling/two-axis rule and axis-only cooldown with evidence-based selection.
- Require actual contact/material effects, keep static no_path compatible with
  movable-object solutions, and expose geometry changes as future adapters.
- Preserve robot/evaluator versions and old evidence. Current code remains guarded;
  source of next development priority is this design, not a completed feature claim.

Delivered role boundaries, full flow, example task/result contracts, stop semantics,
LLM evidence/proposal contents, scheduling/boundary policy, scene validity, cost and
resume requirements, migration stages and acceptance scenarios. This is a project
architecture design, not a new API integration or model migration.

No runtime code edits, paid calls, simulation rollouts, tests, commit or push in
this design task. Documentation links/whitespace checked separately.
