# Ten-call-budget VLM run: wall-contact diagnosis

User requested review only. No controller/prompt/config changes, new rollouts or
paid API calls performed. Existing untracked source/history work preserved.

## Evidence

Run `/workspace/g1_failure/runtime/robot_vlm/20260918T142133_820399Z`.
Verified every original manifest artifact SHA256. Read result, decisions, protocol,
observations and states. Visually inspected the final GIF frame (35.58s).
Recomputed derived geometry/contacts with saved scene.xml and last five recorded
qpos/qvel/ctrl states using mj_forward only (no physics integration/new rollout).
Final recorded state time 35.605s equals result duration, so terminal contact is
represented rather than inferred from an earlier sample.

Result valid_execution=true, success=false, FORBIDDEN_CONTACT; 4 API calls attempted,
3 actions accepted; goal distance 5.141611m. Fourth call has call_started only:
response/action/usage not retained after terminal failure. Do not infer refusal,
API failure or an executed fourth command from its missing response record.

Accepted commands (body frame):
1. vx=0, vy=0, yaw_rate=0.03, duration=1.0s; latency 7.0279s.
2. vx=0.28, vy=0.045, yaw_rate=0.03, duration=1.8s; latency 6.6583s.
3. vx=0.25, vy=0.138, yaw_rate=0.059, duration=2.0s; latency 7.4841s.

## Terminal contact

Phase inference_wait, command [0,0,0]. Reconstructed two contacts:
wall_south ↔ right_hand_index_1_link, distances -0.00061558m and -0.00060432m.
Other near-end contacts are box/floor, not robot/box. Robot final base
[1.878008,-0.448741,0.742231]m; box still well ahead around x=4m.
No falling terminal reason; final frame shows upright robot near south wall.

Fourth observation at 25.795s: base [1.811683,-0.299168,0.744139]m,
yaw -0.328558rad. Until terminal 35.605s (9.81 simulated seconds later), the
zero-command robot drifted south ~0.14957m and forward ~0.06632m.
Earlier observations also show progressively negative y/yaw during repeated waits.
This proves zero commanded gait velocity is not reliable world pose holding here.
It does not establish whether the cause lies in policy training, model/adapter
mismatch, gains or another lower-level detail; those need controlled diagnosis.

## Interpretation and boundary

This is a valid failure of the tested whole stack (VLM + inference latency + gait
waiting behavior), not evidence that GPT chose a colliding fourth action. It is
also not successful box manipulation or failure at the box. Larger call budget
allowed the previously short trial to expose accumulated drift.
Current stale-response checks run after a response arrives; they do not prevent
motion while waiting. Contact termination prevents further execution but is not
predictive avoidance. Report waiting behavior as part of robot-system version.

Possible next controlled investigation: compare zero-command waiting with a
declared local base/yaw-hold controller on the same fixture. Such stabilization,
if later authorized and implemented, is a versioned robot-internal capability,
not a hidden task-specific route. Preserve this failure and avoid crediting any
changed robot result to the original robot version. Improve terminal contact and
pending-call accounting in later code changes; neither was changed in this review.
