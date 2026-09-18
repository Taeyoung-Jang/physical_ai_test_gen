# 2026-09-18 — Robot-side VLM initial integration

## User intent and scope

User authorized introducing VLM into the robot, emphasizing robot autonomy and
AFS's role of discovering environments that defeat a fixed robot system.
No scripted south-approach/push solution or easier replacement scene was introduced.
Implemented movement-only camera-policy loop; manipulation remains unavailable.
Initial git status clean; all files added, no preexisting files changed.

## Implementation

- robot_vlm/policy.py: strict allowlisted Observation and bounded Action, replaceable
  Policy protocol, GPT-6 Astra Responses image+JSON-schema adapter, sanitized failures,
  explicit offline MockPolicy and stale-state/pose checks.
- robot_vlm/runner.py: original clear-path fixture, torso-mounted real camera, raw
  public geometry map and GT pose, CUDA Walk.onnx, async policy decision with gait
  continuing at zero velocity during wait. Independent physical/task evaluation.
- tools/run_robot_vlm.py: mock default, explicit --live, bounded calls/simulation,
  external environment key only, runtime artifact directory and safe error artifact.
- tests/test_robot_vlm.py: image payload, allowlist prevents AFS data leakage,
  action limits, state/pose staleness, one-call mock transport, refusal/incomplete/
  authentication/invalid-schema error sanitization, no-key and explicit mock labels.
- docs/ROBOT_VLM.md: boundary, usage, limitations, provenance and official references.

No navigation reference route, goal placement hint, evaluator success declaration
or AFS context enters the robot prompt. VLM chooses velocity and duration directly;
gait controller is part of the tested robot. Generic robot backend replacement is
still future work; the new policy interface alone is not a universal simulator API.

## API implementation sources and cost boundary

Used OpenAI Docs skill; no API-key helper was available. Consulted official pages:
https://developers.openai.com/api/docs/guides/images-vision
https://developers.openai.com/api/docs/guides/structured-outputs
https://developers.openai.com/api/docs/models/gpt-6-astra

Default gpt-6-astra, explicit configurable model, store=false, image data URL,
strict JSON schema, 2048 output-token cap, fixed official endpoint, no retries.
No real API calls or key inspection during implementation. Mock transport keys
are test-only strings. Live run must be explicitly requested via --live and sends
the recorded camera/public map to OpenAI. Live access/performance is unverified.

## Validation

`pytest tests/test_robot_vlm.py tests/test_clear_path_contact.py tests/test_clear_path.py -q`:
30 passed, 7.20s. Ruff checks passed for added Python files.

First GPU wiring run:
`/workspace/g1_failure/runtime/robot_vlm/20260918T134710_684195Z`
Command `.venv/bin/python tools/run_robot_vlm.py --max-calls 2 --max-seconds 8`.
Actual CUDAExecutionProvider, two observations/two accepted mock movement actions,
4.035s simulation, zero API calls, valid_execution=true, success=false,
BUDGET_EXHAUSTED, final goal distance 5.93924m. This is expected budget-limited
wiring evidence, not autonomous VLM navigation. Source run/artifacts preserved.
Inspected camera_000.png: front-facing box/corridor visible; upper image has self-
occlusion from the current mounted camera. No privileged reporting camera used as input.

After first run, added video policy-origin overlay, explicit call-start records,
gait-code provenance and replaced overly broad autonomous_vlm_validated field with
live_actions_accepted/autonomous_task_success_validated. These refinements do not
change motion selection. A second smoke run verifies the final implementation.

## Remaining limits / next step

First live bounded call must verify actual GPT image reasoning/schema/latency.
Inference continues gait, rejects >15cm translation or >0.2rad heading drift.
30s response deadline stops the loop, but HTTP thread cleanup can outlast it until
the per-operation timeout; remote spending cannot be cancelled retroactively.
No self-collision classification, manipulation, full navigation success, generic
robot backend, AFS suite integration or fair Random-vs-AFS comparison is claimed.
After live wiring, freeze robot model/prompt/controller/observation version for AFS.

## Final smoke evidence

Final implementation run: `/workspace/g1_failure/runtime/robot_vlm/20260918T134945_285183Z`.
Same two-call mock GPU protocol completed with BUDGET_EXHAUSTED (not goal success).
All original artifacts are preserved; report includes video/GIF and camera input.
