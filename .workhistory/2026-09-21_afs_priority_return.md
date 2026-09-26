# AFS priority return — 2026-09-21

User direction: stop prioritizing robot capability development and return to AFS.
No new paid calls, GPU rollouts, or robot-controller changes in this review.

Read PROJECT_ROADMAP.md, PROJECT_INTEGRATION_AUDIT.md, EXPANDED_LLM_AFS.md;
cross-checked expanded.py and goal_runner.py entry points. September 6 roadmap
is historical: newer terrain generation and LLM proposal/feedback already exist.

Current gap: expanded AFS compiles terrain suites and imports isolated terrain
runner feedback; robot goal runner constructs clear_path.fixture directly and
uses its fixed object/wall IDs and goal. These are not a connected arbitrary-scene
VLM/push evaluation pipeline. Do not imply existing suite files run through it.

Next bounded milestone: connect one explicitly versioned scene-domain/backend
to proposal -> candidate validation -> fixed robot execution -> typed outcome ->
feedback -> next-round proposals, then compare Random/Sobol on that same domain.
Prefer existing terrain backend for the first full loop to avoid another robot
development detour. This evaluates GT-map/pose CUDA gait, not the VLM/push robot.
VLM/push backend requires a distinct scene adapter and supported mutation domain;
keep it a separately identified extension, never silently substitute controllers.

Evaluation must separate task failure, invalid scene, infrastructure/model errors,
and budget termination; under a predeclared call-budget task, exhausted calls with
unmet goal can be counted as budget-conditioned noncompletion, not collision/fall.
Record valid evaluation counts plus total attempts, invalids, cost and retries.
Preserve robot/config/evaluator identity and videos; no superiority claim from a
single-seed pilot. Do not train/search on one robot and label results as another.

This file records scope/audit only, not implementation of a campaign driver.
