# Live push/alignment result review — 2026-09-21

Run reviewed: `/workspace/g1_failure/runtime/robot_goal_agent/20260921T155205_243359Z`.
Read-only artifact/source analysis; no new simulation/API call or controller edit.

## Outcome

- valid_execution=true, success=false, BUDGET_EXHAUSTED; 10 calls and 10 accepted actions.
- All ten recorded responses HTTP 200; response latency about 7.68–49.35 seconds.
- Simulation duration 318.375 seconds; final goal distance 3.6554 m.
- Actions: plan, navigate twice, push request, push retry, plan, retreat/recenter,
  plan, lateral/yaw correction, final push. Last route query returned no_path;
  there is no route recheck after the final push, so final path opening is unverified.

## Alignment attempt (003)

Forward gap improved 0.95553 -> 0.87770 m; lateral error 0.05713 -> 0.01343 m.
Stopped at 1.68 seconds with alignment_motion_limit, cumulative planar travel
0.200114 m. Final instantaneous readiness=true, but controller checks motion
limit before its continuous 0.25-second stability completion condition.
Travel sums every planar base increment (including gait oscillation), rather
than net displacement; net displacement from the projected gaps is about 8.9 cm.
This is a conservative guard/controller issue to investigate, not successful
automatic alignment-to-push handoff. Next GPT call explicitly used numeric
readiness feedback and retried; original preflight passed without alignment.

## Physical pushes

- 004: requested 15 cm; actual forward displacement 7.908 cm; target error
  7.096 cm; contact 6.805 seconds, peak force 28.617 N; released and handoff complete.
- 009: requested 10 cm; actual forward displacement 7.116 cm; target error
  2.885 cm; contact 7.075 seconds, peak force 27.053 N; released and handoff complete.
- Both valid but success=false / DURATION_REACHED: current skill requires <=2 cm
  target error. These are local skill-duration completions, not HTTP timeouts.
- Final box position approximately (4.15008, 0.00244, 0.34994), vs initial (4,0,...):
  about 15 cm total forward motion. Physical movement does not establish path clearing.
- No safety terminal reason recorded in these skill results. Final robot base
  (3.34802,-0.15813,0.74136); no fall/safety termination reported by run result.

## Interpretation / next work

Real model selected pushes and physical execution occurred, unlike the previous
preflight-only rejection. Numeric feedback was used to retry. This single run
does not validate reliable pushing, automatic alignment completion or full task success.
Investigate oscillation-sensitive alignment travel accounting/stability and the
push distance achievable within its internal phases before simply raising API budget.
Keep robot versions separate when comparing AFS outcomes. Do not relax safety or
success thresholds solely to turn this result into success.

Visual artifacts exist: report.html, rollout.mp4, rollout.gif, and camera frames.
This review used JSON/source evidence; videos were not visually inspected.
