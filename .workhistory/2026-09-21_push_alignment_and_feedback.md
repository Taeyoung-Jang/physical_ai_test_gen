# Bounded pre-push alignment and quantitative feedback

User authorized implementation of next steps1/2 after stopping experiment execution.
No GPU rollout, paid API call, external mutation or new runtime experiment performed.
Only code/documentation changes and CPU unit/regression tests.

Implemented robot_vlm/push_alignment.py: numeric readiness (errors, limits, checks),
bounded alignment controller, stable-readiness interval and distinct stop reasons.
push_execution.align dispatches through the existing guarded runner step. Selected
object/target remain GPT-owned. Correction runs without hand/object contact exemption
and with neutral arms; original6cm/.12rad push limits are unchanged.

Entry band: gap .72–.98m, lateral<=.14m, heading<=.20rad, valid shape/height/face/target.
Caps:8simulation seconds,20cm cumulative planar travel,.25rad yaw change. Before
push, tighter3cm/.06rad alignment held.25s is required.29s remaining is required if
correction is needed; direct push still21s. State/object freshness is checked each
step, and safety stops take precedence before any further correction. No remote
calls are made during alignment. No teleport or synthetic progress in production.

Runner records readiness_before/after and alignment summary into skill result/history;
alignment_NNN.jsonl records progress and terminal reasons. API capability text explains
bounded correction and pending physical validation. Robot protocol/prompt/controller
condition advanced to v4 and source hash includes alignment module. Legacy no-push
controller remains unchanged. No broad approach/path solution is injected.

OpenAI Docs skill used to inform clear capability/result descriptions; official
function-calling guide consulted without changing the existing structured command API.

Tests cover the recorded3.60cm->7.17cm drift, JSON numeric feedback, sign/caps/stable
hold reset, timeout/range/travel stops, budget rejection, stale object and safety
stop. Fake-kinematics convergence tests validate orchestration only, not robot gait.
Initial relevant suite60passed/3GPU-skipped; expanded final regression recorded in
this turn. Ruff and whitespace checks pass. Documentation ROBOT_PUSH_ALIGNMENT.md.

Outstanding: physical correction/settle/contact-free convergence and end-to-end
real-GPT selection must be tested only when user resumes runs. Existing lateral
gait response may not track ideal velocities; no claimed physical fix yet. Do not
merge v3/v4 AFS results without distinguishing robot condition. Readiness_after is
relative to the original requested target and need not be true after a successful
push has already reached that target.
