# Goal agent live run: transport/schema ambiguity review

User requested reviewing run 20260918T150722_325742Z. No implementation change,
new robot execution or paid call performed. Inspected saved records and local code.

Run path: `/workspace/g1_failure/runtime/robot_goal_agent/20260918T150722_325742Z`.
Result: valid_execution=false, success=false, transport_or_schema_error,
4 calls attempted, 3 accepted actions, 74.335 simulated seconds, goal distance 5.41356m.

Accepted GPT decisions:
1. Query path to [7,0]; robot planner returned no_path. API latency 9.2796s.
2. Choose navigate_to [2.7,0], duration 3s, intending inspection near the box.
   Execution slice ended at base [1.445206,-0.027675,0.742976]; latency 23.3374s.
3. Choose navigate_to [2.7,0.25], duration 5s, continuing toward a staging point.
   Execution slice ended at base [1.583972,0.089927,0.742241]; latency 20.6375s.
4. call_started only; no parsed action, raw response, status or exception category saved.

Final sampled state: 74.300s, inference_wait, base [1.586776,0.101593,0.741907].
Current run stopped for infrastructure/protocol error, not recorded wall contact/fall.
Do not claim goal/staging arrival: both navigate_to slices ended before target arrival.

## Confirmed diagnostic limitation

GoalPolicy.decide catches httpx.HTTPError, ValueError (including Pydantic validation),
KeyError and TypeError together and emits transport_or_schema_error. Neither the
exception subtype nor validation locations nor HTTP response metadata survives.
Therefore exact cause cannot be recovered from this artifact set. In particular,
do not infer invalid key (three calls succeeded), network timeout, or a specific
invalid fourth action without evidence.

## Reproduced contract defect, not proven incident cause

GoalAction.model_json_schema declares duration_s between 0.2 and 10 for all actions.
Its custom validator restricts move duration to <=2 and imposes additional cross-field
rules not represented in that JSON schema. Offline example move, vx=.1, duration=3,
target=null, skill_request=null passes jsonschema.validate but fails GoalAction validation.
This explains one possible route to the generic error. The actual fourth response
was not saved, so it cannot be attributed to this defect conclusively.
Follow-up should align API/local action contracts and distinguish sanitized error
categories before spending another live run. Do not silently widen motor action limits.

## Artifact integrity finding

Checked manifest hashes: all entries match except rollout.mp4. Did not modify/rewrite
the manifest or video. Cause of mismatch is unknown; do not call this video verified
or infer tampering/corruption. JSON/GIF/observation/state entries matched. This issue
is separate from the earlier policy failure; source records are still informative.

No keys or unrelated credential stores read. Existing source/user work preserved.
