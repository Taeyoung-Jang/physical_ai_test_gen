# Fix shared robot API contract/diagnostics and failure-path artifacts

User explicitly requested fixing transport_or_schema_error and similar issues broadly.
Clarified internal planner WAS used in earlier plan_path/navigate_to calls; no planner
activation change required. Preserved all old runs, API behavior evidence and user work.

## Changes

Added wire_contract.py: action-specific nested union envelope with shared typed API/
local validation; max 2s raw movement retained, navigation max 10s retained, null/zero/
length/skill constraints now present in JSON schema. No widening safety thresholds.
Added api_transport.py: common v1/v2 HTTP transport and safe staged diagnostics. No
automatic retries. Request/response identifiers, tokens/hash/size and validation
locations retained; keys/raw HTTP/exception text/inputs/unknown field names omitted.
Both policy versions now use the shared transport and envelope parser. Incremented
prompt and loop protocol versions, added new source file hashes. Model choice unchanged.

Both runners explicitly close video in finally. Inspected installed imageio source:
writer.__exit__ calls close only when no exception occurred. Thus original error
unwinding could leave ffmpeg finalization until after manifest hashing. Fixed this
mechanism; original MP4/hash mismatch preserved rather than overwritten.
Also record terminal qpos/qvel/contact identities and late pending-call outcome,
including usage if available, without executing a response after termination.

Added tests/test_robot_vlm_failures.py and docs/ROBOT_API_RELIABILITY.md. Updated mock
HTTP fixtures to the new envelope. Existing schemas/runner-visible flat actions remain
compatible with historical logs, but new API requests expect the envelope deliberately.

## Evidence

Initial offline regression: 56 passed, 1 explicit GPU test skipped, 6.72s.
GPU error injection:
- runtime/robot_error_checks/20260918T155351_052420Z: schema error, recorded diagnostics,
  final MP4 decoded and artifact hashes verified; 1 passed in 16.41s.
- runtime/robot_error_checks/20260918T155534_762504Z: repeat schema-error finalization.
- runtime/robot_error_checks/20260918T155542_690053Z: delayed mock response after simulation
  budget; pending_call completed_after_termination, executed=false; hashes verified.
  Combined GPU tests: 2 passed, 31 deselected, 22.95s.
Normal GPU goal-agent regression:
runtime/robot_goal_agent/20260918T155530_977482Z, 2 mock calls, BUDGET_EXHAUSTED,
not a GPT success claim. Zero paid calls across all tests.

Test commands from scene2test:
`pytest tests/test_robot_vlm_failures.py tests/test_robot_goal_agent.py tests/test_robot_vlm.py -q`
`MUJOCO_GL=egl SIM_SERVER_ONNX_PROVIDER=cuda RUN_ROBOT_ERROR_GPU=1 pytest tests/test_robot_vlm_failures.py -k gpu -q -s`

## Scope / uncertainty / source

Original response 4 from 20260918T150722_325742Z is unavailable. Cannot retrospectively
declare its exact cause. Fixed the reproduced schema disagreement and diagnostic/video
failure-path defects; future transport failures remain possible and are now identifiable.
Current agent OPENAI_API_KEY presence check: absent. No key value/credential store read.
User can rerun the same live command in their configured terminal; no automatic live spend.

OpenAI Docs skill used to verify supported structured-output shape:
https://developers.openai.com/api/docs/guides/structured-outputs
Root object plus nested anyOf chosen rather than unsupported root anyOf/if-then rules.
No new model, route, environment, external interventions or manipulation capability.
All preexisting source files were untracked from earlier work; read exact contents and
used apply_patch to preserve unrelated contents while making scoped replacements.

## Final verification

Expanded regression suite including robot policy, clear-path probes/placement and terrain
guards: 90 passed, 2 GPU tests skipped by default, 19.79s. Both GPU tests were run explicitly
and passed as recorded above. Ruff passed. Final wire hardening uses strict numeric zero
bounds instead of literal-zero annotations to reject boolean-as-zero inputs. Related API
regression rerun passed (56 passed, 2 explicit GPU skips). CLI and paid-call budget unchanged.
