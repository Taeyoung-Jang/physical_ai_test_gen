<!-- Stage-1 record; current opt-in integration is documented separately. -->

Current update: the short push skill is now wired behind `--enable-push`.
See [ROBOT_PUSH_INTEGRATION.md](ROBOT_PUSH_INTEGRATION.md). The stage-1 implementation
and original limitations below are retained as historical context.

# Experimental robot-local near-contact push

This is the first skill implementation stage, not a complete manipulation robot.
The existing GPT goal-agent command is unchanged: this skill is NOT yet advertised
or dispatched by its live runner. Grasp/carry/jump remain unavailable.

## Implementation

`robot_vlm.push_skill.PushSession` accepts a caller-selected object ID, measured
robot/object poses, box dimensions and a world-coordinate target. It supplies palm
targets and body-frame velocity commands to the existing `ArmGaitController`:
scratch-state arm IK, rate-limited upper-joint actuator targets and CUDA Walk.onnx
lower-body gait. The runtime object is advanced only by MuJoCo contact dynamics.
No object relocation, artificial object attachment or injected object forces.

The initial contract deliberately requires an already aligned near-box approach:

- Box dimensions 0.8 x 1.1 x 0.7 m; upright face aligned within 0.12 rad.
- Requested displacement 0.075–0.20 m along the robot's approximately forward axis.
- Base-to-box center forward separation 0.72–0.90 m, lateral offset <=0.06 m.
- Base height 0.65–0.85 m, box center height 0.30–0.40 m.
- Force feedback slows the existing supervisor above 40 N per contact; 120 N
  per-contact hard stop is enforced by the physics runner. This is not impedance control.

The controller runs settle/reach/push/retract/released-hold. Target displacement or
the 13-second timeout initiates retraction. The validation run is normally 18 s.
Success requires target XY error <=0.02 m, measured push contact, continuous hand
release >=0.5 s, sufficient execution duration, valid physics, no force limit or
fall/forbidden-contact termination. Measured progress without reaching the target
is not success. Support bounds are preconditions, not success guarantees.

Coordinate-rotation equivariance is unit tested; physical evidence is only for the
recorded forward-facing fixture. General approach, arbitrary boxes, side placement,
self-collision classification, grasping and jumping are not validated. IDs must be
resolved to a dynamic object by the host; the validation host binds `clear_box`.

## Validation commands

From scene2test:

```bash
uv run python tools/run_robot_push_validation.py
uv run python tools/run_robot_push_validation.py --initial-y 0.02
uv run python tools/run_robot_push_validation.py --mass 8 --friction 1.2
```

Runs save under `/workspace/g1_failure/runtime/robot_push_validation/<timestamp>`:
MP4, GIF, final frame, report.html, state/control/contact logs, skill result,
requested target, source/asset hashes and manifest. No API calls. The runner starts
at x=3.2 next to the box BEFORE stepping; this is explicit test setup, not autonomous
approach evidence. The green legacy bay marker is not this unit test's target.

`push_validation.py` is an isolated adaptation of the existing contact probe, with
the new session replacing its fixed supervisor. Legacy probes, GPT loop, server and
AFS are unchanged. Shared safety/finalization fixes should be kept consistent until
probe runners are consolidated.

## Next integration gate

Introduce a separately versioned, opt-in robot capability contract and typed
push action; expose preconditions honestly to GPT. Preserve the original spawn and
let GPT choose whether/where to approach and what object target to request. Host
execution must reject unsupported poses, permit ONLY designated hand/object contact
while the skill is active, retain all other guards, report actual object pose and
replan from changed geometry. Do not hard-code a route to the side bay or promise
this short forward-push primitive solves the blocked corridor. Demonstrate controller
handoff/retraction and normal navigation after skill completion before live release.

For AFS, freeze the resulting robot version and distinguish goal noncompletion,
physical failure, unsupported capability and infrastructure-invalid execution.

