# Opt-in GPT push integration

## Scope and changes

User approved connecting the validated near-contact push primitive to the goal agent.
Added push_policy.py with typed PushAction/PushEnvelope and capability-aware prompt;
push_execution.py resolves the selected dynamic geometry and enforces preconditions.
CLI `--enable-push` selects the new policy and arm/gait controller; absent flag retains
the original policy/schema/controller. Goal runner records a separate v3 protocol,
controller condition, original initial XY and new dependency hashes.

The same controller/data/ONNX history are retained across actions. Only active-skill
hand/selected-box contacts are allowed. Contact force, fall, external-force and numerical
guards remain active. Object freshness/tilt/geometry, alignment, displacement and a full
21-second remaining budget are checked before beginning. Failure to release terminates;
released hands are returned to neutral with rate-limited targets during a 3s base hold.
Subsequent contacts have no push exemption. Measured skill results and updated real
geometry are fed back to the robot policy. No scripted approach or placement is injected
into production prompts/execution. No live API calls, scene modifications or AFS changes.

Used OpenAI Docs skill and official structured-output guide for nested typed action union.
Mock transport verifies actual policy request construction, schema parsing and history.
Model remains gpt-6-astra; default per-call deadline remains 30 seconds.

## Validation and honest boundaries

83 unit/regression tests passed, 4 GPU-only tests skipped; 19 existing clear-path tests
passed separately. Ruff and git diff --check pass after formatting.

First GPU integration pair passed (2 tests, 105.67s):
- near-box test setup: runtime/robot_push_integration/20260918T171951_946630Z
- original spawn: runtime/robot_push_integration/20260918T172035_120683Z

Both physically pushed ~8cm, released hands and completed handoff. Original-spawn
target error ~2.64mm. However, its post-push navigation returned blocked_endpoint because
the robot was within the conservative inflated box clearance. This is preserved, not
declared successful path following. The mock test was expanded to exercise a short raw
backward movement before planning/navigation, without adding that strategy to GPT.

Second pair:
- near-box: runtime/robot_push_integration/20260918T172437_765283Z
- original spawn: runtime/robot_push_integration/20260918T172520_953600Z

These are deterministic wiring/physics tests, not autonomous GPT runs or proof of clearing
the corridor. Production GPT still chooses whether to attempt pushing, where to approach
and how to recover. Full task success remains false in these blocked-corridor smoke tests.
No grasp, carrying, jumping, arbitrary box geometries or sideways placement is advertised.
Self-collision classification remains unimplemented. Next user live run tests the new
schema with the real API and the model's own action choices, with existing detailed logs.

Artifacts include MP4/GIF, camera inputs, decisions, per-call diagnostics, contacts,
skill_NNN.json, protocol, result and manifest. Existing failures/evidence preserved.
Documentation: scene2test/docs/ROBOT_PUSH_INTEGRATION.md.
