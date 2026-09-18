# Robot-side VLM adapter v1

2026-09-18. Implements camera observation → policy decision → bounded G1 velocity
execution → fresh observation. This is a separate robot policy, not an AFS policy.
No new scene, hand-coded route, south-push instruction or manipulation skill is added.

## Boundaries

- AFS/test system owns scene/task generation and independent result evaluation.
- Robot policy receives RGB, full geometric map, GT base pose, goal and prior action
  execution status. No AFS hypothesis, reference path, future result or hidden mass/
  friction is supplied. The map contains raw wall/floor/box geometry, not a solution.
- VLM selects body-frame velocity/duration directly. No waypoint planner supplies
  the answer. Existing CUDA Walk.onnx supplies joint-level gait control.
- Actions: move, observe, stop. Limits: vx [-0.2,0.3]m/s, vy [-0.15,0.15]m/s,
  yaw rate [-0.4,0.4]rad/s, duration [0.2,2]s. No push/grasp/teleport.
- Policy is replaceable through `Policy.decide(Observation, png)`. The current
  execution backend is G1/MuJoCo-specific; a universal robot backend is NOT complete.
- This is RGB+GT-map+GT-pose, not VLM-only localization or SLAM. The map can bypass
  visual ambiguities, so vision contribution needs a later ablation.

## Commands

Use the existing GPU environment from `scene2test`:

```bash
# No API calls. Hard-coded forward mock for wiring only, NOT VLM evidence.
uv run python tools/run_robot_vlm.py --max-calls 2 --max-seconds 8

# Explicitly enables paid API calls and sends camera images/public geometry.
# OPENAI_API_KEY must already be set in the invoking shell; never pass it as an argument.
uv run python tools/run_robot_vlm.py --live --model gpt-6-astra --max-calls 2 --max-seconds 60
```

Model defaults to `gpt-6-astra`; override is explicit and recorded, never an automatic
fallback. No keys, dotenv content, auth headers, raw HTTP errors or secret values
are saved. No auto-retry, custom endpoint, redirect or AFS context reuse.
API call cap 1..20 (default 10); simulation cap 3..120s (default 30); 2048 maximum
output tokens per call. These are request limits, not a currency spending estimate.
Responses timeout: 30s per HTTP operation. The loop rejects a response not ready by
its 30s wall deadline, but thread cleanup can wait for the in-flight HTTP call to
finish/time out. Cancelling locally cannot cancel already incurred remote charges.

## While awaiting the VLM

Physics and CUDA gait continue with zero commanded velocity, not paused simulation.
Zero velocity is not a guaranteed stationary pose. Response state_version must
match and base drift must be <=0.15m, yaw drift <=0.2rad. Otherwise the command is
discarded and the policy receives a fresh observation with stale-rejected feedback.
No automatic substitute action or reference route is inserted. Inference wait is
paced at no faster than simulation dt; rendering can make it slower than wall time.
The simulation budget includes inference-wait steps.

Fall, forbidden robot/world contact and numerical errors stop the trial. Allowed
contact is foot/floor only. Self-collision classification is not implemented.
The independent evaluator requires reaching within 0.25m of the task goal for 1s
without failure. It never accepts a model assertion of success.

Schema/transport/refusal/missing-key errors are infrastructure/indeterminate, not
AFS-discovered physical failures. Valid stop or exhausted action budget without
goal reaching is an unsuccessful robot episode. Stale rejected decisions consume
the call budget. Partial observation/video artifacts remain if infrastructure fails.

## Evidence

Default outputs: `/workspace/g1_failure/runtime/robot_vlm/<UTC>/`:
protocol + resource audit + XML, numbered robot camera PNG/observation JSON,
decision/latency/usage log, actual qpos/qvel/ctrl/command trajectory, MP4/GIF,
result/report and artifact hashes. Video distinguishes mock/API policy origin.
The camera has partial self-occlusion in the current robot asset; this is preserved,
not replaced by a privileged overhead image. Overhead video is reporting only.

Offline tests use HTTP mock transport, including actual image request payload,
structured outputs, invalid actions, staleness, refusal and error sanitization.
GPU mock execution validates wiring only. Real GPT live inference and autonomous
goal-reaching have NOT yet been validated. The current fixture is intentionally
blocked by a box and this robot has no manipulation action: failure is legitimate.
The mock is not a baseline for measuring AFS superiority.

## Official API contract consulted

OpenAI Docs guided image-input and strict structured-output integration:
[images and vision](https://developers.openai.com/api/docs/guides/images-vision),
[structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra).
Account access must be verified by the user's explicit live run; it is not inferred
from model documentation or mocked transport success.

## Reliability update (2026-09-18)

API/local action schemas and diagnostic/video failure handling were corrected after the
initial implementation. See [ROBOT_API_RELIABILITY.md](ROBOT_API_RELIABILITY.md).
The existing CLI is unchanged; new requests use an action-specific command envelope.
