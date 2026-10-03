# Push alignment and numeric readiness feedback (v4)

Implementation/unit-test stage only. No new GPU simulation or paid API execution
was performed for this change, as requested. Physical validation is still pending.

## Boundary

GPT continues to select the object, target and strategy. The push executor may now
correct small near-contact pose errors immediately before starting the existing
18-second push. It does not navigate from afar, select a side-bay strategy, move the
object directly or relax the original push preconditions. `--enable-push` opts into
the updated v4 robot condition. Navigation-only mode is unchanged.

The original push lateral/heading tolerances remain6cm/.12rad. If preflight fails
only due to pose alignment, internal correction is eligible within forward center
gap .72–.98m, lateral error<=.14m, heading error<=.20rad and all non-pose conditions.
Correction is bounded by8s,20cm accumulated planar base travel and.25rad yaw change.
Its desired center gap is.82m. Translation commands in the push frame are bounded
to.06m/s forward and.08m/s lateral; yaw command to.15rad/s. These are implementation
limits, not demonstrated physical capabilities.

The correction must achieve original push eligibility plus lateral<=3cm and
heading<=.06rad continuously for.25s before handoff. Inputs/target are not rewritten.
Actual state is rechecked every physics step, including original observation-relative
object freshness/tilt checks. A full29s remaining budget is required if alignment is
needed (8alignment+18push+3handoff); direct ready pushes still need21s.

During correction active_push is None: NO hand/object contact exemption. The runner's
existing contact/fall/numerical/external-force guards remain in force. Time/motion/
entry-range/stale-object/budget failures return to GPT without executing a push;
an episode safety stop remains terminal. No extra API call is made within alignment.

## Evidence returned

skill_NNN.json and policy history now contain readiness_before/readiness_after:
signed forward/lateral/heading error, box-face error, requested distance/heights,
limits, per-condition booleans and ready/correctable flags. Alignment summary records
attempt, status, start/final measurements when available, elapsed time and travel.
alignment_NNN.jsonl logs progress at approximately20Hz and termination, and existing
states/video record phase push_alignment when experiments are resumed.

Distinct reasons include alignment_timeout, alignment_motion_limit,
alignment_out_of_range, alignment_insufficient_budget and alignment_safety_stop;
stale_object_pose and original preflight reasons remain distinct. Success of alignment
does not mean successful pushing or route clearance.

## Verification scope

### Inclusive distance endpoints corrected on 2026-10-03

Preflight and readiness now share `push_skill.supported_push_distance`. Nominal
displacement limits remain 0.075–0.20m inclusive, with an absolute numerical tolerance
of 1e-9m (one nanometre) at those endpoints only. No relative tolerance is used.
Readiness reports it as `limits.push_distance_abs_tolerance_m`; the raw measured
distance and GPT's target are retained, not rounded or clamped. Nonfinite distances
and real out-of-range requests remain rejected. Pose, contact, time and travel
guards are unchanged.

The reviewed nominal 20cm request measured 0.20000000000010654m and previously failed
before alignment. It now passes the distance gate, but its lateral error still
requires alignment: it does not become an immediately executable push. The later
15cm request with 14.54cm lateral error still cannot enter the 14cm alignment range.
CPU endpoint/rotation/saved-input tests and fake-kinematic dispatch cover the fix;
they do not prove that live G1 alignment, pushing or goal completion will succeed.

Both changed modules are already covered by protocol source hashes. Controller
family names stay the same, but this is a NEW robot condition. Preserve old FAILs;
do not resume old frozen suites with changed code or combine their outcomes into
a same-condition boundary. See the
[implementation and verification record](../../.workhistory/2026-10-03_push_distance_numeric_fix.md).

### Existing alignment coverage

Tests cover the saved3.60cm versus7.17cm alignment case, JSON-safe numeric feedback,
correct correction direction, stable-hold reset, motion/time/range caps and guarded
dispatch using fake kinematics. Fake callback motion is ONLY a unit-test mechanism;
production continues to use actuator-driven MuJoCo stepping. A real G1 gait may move
sideways slowly or oscillate, and accumulated travel may hit the cap before converging.
Those physical questions await explicitly resumed GPU testing. Do not mix historical
v3 robot results with v4 AFS measurements.

OpenAI Docs skill informed the capability description/result feedback wording:
https://developers.openai.com/api/docs/guides/function-calling . The existing structured
command API is retained; this change does not migrate to a different tool-call protocol.
