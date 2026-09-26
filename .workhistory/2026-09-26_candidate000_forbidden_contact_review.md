# Candidate 000 baseline review — FORBIDDEN_CONTACT — 2026-09-26

Run: `/workspace/g1_failure/runtime/robot_goal_agent/20260926T130019_070486Z`.
AFS candidate: `/workspace/g1_failure/runtime/behavior_afs/20260926T123153_802880Z/candidate_000.json`.
Read-only artifact review; no rerun, code change or API call.

## Run validity/outcome

Result: valid_execution=true, success=false, FORBIDDEN_CONTACT, 10/10 calls,
simulation 229.145s, terminal goal distance 3.70279 m. This is a valid task
failure under current contact policy, not a numerical/API error and not a fall.
All ten API calls reported completed HTTP 200 in per-call logs. Artifact manifest
contains the recorded outputs including rollout GIF/MP4, though this review's
causal determination relied on structured contact/skill logs and source contract.

## Action sequence and behavior

0 planner reports no_path from spawn; 1–2 approaches to the west side of box;
3 short +x approach. Call 4 requests 0.18m push to [4.18,0]. Built-in alignment
completes in 1.735s / .188m accumulated path; lateral error falls .0812 -> .0226m.
First push moves box +.0760m X / +.0128m Y, only 42% of requested forward distance;
6.76s allowed hand contact, peak 31.0N, then skill says released and returns
DURATION_REACHED, target error .1048m. Goal route remains no_path.

Call 6 tries a +Y adjustment. Call 7's push is rejected before contact because
lateral offset .1420m exceeds the .14m correctable-entry limit. Call 8 recenters.
Call 9's new .18m push passes readiness, but moves only +.00363m X / -.00288m Y
before run termination. It does not clear the route; goal remains 3.70m away.

## Exact terminal cause

Only one forbidden-contact row exists:
time 229.145s, phase `push_handoff`, robot geom 79 = `left_hand_index_1_link`,
world geom 110 = selected `clear_box_geom`, contact distance -2.5038e-6m.
Thus fingertip penetrated the selected box by about 2.5 micrometers during handoff
from the skill controller to the neutral arm target. It was not forbidden wall,
floor, other-object or nonselected-object contact. Terminal-state contacts also
show the same pair. It is a genuine guard-triggered contact event under the current
strict policy, but stored normal_force_n is null because no force was sampled for
disallowed contact; do not infer impact severity from this event.

`push_execution.permitted()` only grants hand-box contact while the session is
active and its subphase is reach/push/retract/released_hold. In `goal_runner.py`,
the skill result is created, `active_push` is set None, then phase `push_handoff`
commands arm targets back toward neutral while box contact is disallowed. The arm
can still be physically near/in contact as its position controller transitions.
This isolates the immediate failure to post-skill hand clearance/handoff behavior,
not a robot fall. Whether the contact is a harmless graze or harmful collision is
unknown; force/impulse must be recorded before judging severity.

## Research interpretation

Candidate 000 is the unchanged 2kg / box friction .5 / floor friction .8 scene.
It establishes baseline noncompletion under this run's policy choices and contact
contract. Earlier same nominal scene (20260921T155205_243359Z) ended BUDGET_EXHAUSTED
after 2 pushes moved the box ~15cm. Outcomes differ, underscoring the need for repeat
baseline and action-path-conditioned reporting. No scene-factor boundary is inferred
from candidate 000 alone. It also reveals the next failure mechanism to test: contact
after skill release during handoff. Scene material AFS will not discover this by
changing mass/friction alone; first improve contact telemetry or expose handoff as a
measured outcome while preserving the fixed robot condition.

Source references: `robot_vlm/goal_runner.py` immediate contact guard and handoff;
`robot_vlm/push_execution.py:permitted`; `robot_vlm/push_skill.py:result`;
`clear_path/contact_control.py:released_hold`.

Reporting defect: `result.json.note` is hardcoded to “Mock proves wiring only” even
when protocol/result origin is `openai_api`; report.html similarly says “Mock is NOT
VLM evidence” for every run. This output is misleading for this live run and should
be corrected in a separate implementation change. For current interpretation, trust
protocol.policy_origin, call logs, and live_actions_accepted rather than that note.

AFS implication: the next search should first distinguish and reproduce the
push_handoff hand-box contact mechanism, while logging its force/impulse. A mass or
friction change cannot explain this immediate trigger from these data. The current
behavior AFS summary does not extract `contacts.jsonl` forbidden-contact pair and
phase as a structured failure mechanism; that parser gap must be addressed before
expecting the AFS prompt to prioritize this particular cause.
