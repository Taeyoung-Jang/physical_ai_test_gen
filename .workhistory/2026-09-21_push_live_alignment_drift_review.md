# Live push request rejected after inference-time alignment drift

Run `/workspace/g1_failure/runtime/robot_goal_agent/20260921T143353_478544Z`.
Analysis only; no code/scene changes, API calls or retries.

Result valid_execution=true, success=false, BUDGET_EXHAUSTED;10 calls/10 syntactically
accepted actions;278.4 simulation seconds;3.8207m remaining. All10 requests HTTP200,
latencies16.875–53.326s. No timeout or collision/fall termination. All46 artifacts
match manifest SHA256. The unlimited simulation setting worked.

Actions: goal-path query(no_path); three navigation slices toward the west face;
five small forward/lateral/yaw corrections; final push_object targeting[4.15,0].
The push command parsed successfully but executor preflight rejected it with
near_aligned_approach_required. No physical push was executed and box stayed at[4,0].
live_actions_accepted counts command/freshness acceptance, not successful skill execution.

## Exact preflight comparison

Observation009 at simulation260.46:
base[3.17543865,-.03596943,.74166042],yaw.018252rad.
Forward center separation .824561m, lateral separation .035969m. Running actual
push_skill.preflight on this saved observation returns None (eligible).

Execution at simulation278.4 after20.226wall seconds:
base[3.17997032,-.07171399,.74222076],yaw.008937rad.
Forward separation .820030m remains inside[.72,.90]; lateral .071714m exceeds.06m.
Position drift magnitude .036035m. Running the same preflight returns the saved
near_aligned_approach_required result. Thus GPT's stated eligibility was consistent
with its observation; waiting changed the precondition before execution.

Generic freshness threshold .15m/.2rad accepts this drift, while skill alignment
requires <=.06m lateral gap. Both guards behaved as coded but their tolerances and
inference-time pose holding are not sufficient for reliable near-contact execution.
The first1s lateral command barely improved y; the later2s command improved y from
about-.1324 to-.0360. Do not assume commanded velocities equal actual displacement.

No remaining call was available to react to the rejection. Removing time limits did
not remove max-calls10. This is valid task noncompletion in current result semantics,
distinct from API infrastructure errors and from failed physical pushing.

Recommended scope: skill-specific freshness/readiness feedback with numeric errors,
better inference-time pose holding or a bounded robot-internal alignment executor
that respects existing contact checks. Do not silently loosen6cm preconditions or
claim merely adding calls fixes the boundary. Target15cm is inside advertised request
bounds but previous physical success evidence was approximately8cm;15cm pushing is
not validated by this run. Freeze/version any robot-system changes for AFS comparisons.
