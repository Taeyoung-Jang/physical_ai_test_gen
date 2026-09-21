# Robot API reliability correction — 2026-09-18

Applies to the existing velocity runner (v1.1) and goal-agent runner (v2.1).
Launch commands and budgets are unchanged. Existing runtime evidence is never rewritten.

## Fixed contract mismatch

Responses now emits `{"command": {...}}`. An object root contains a nested union of
typed action-specific variants. The same Pydantic variants generate the API schema
and validate the returned object. The runner still receives the original flat Action/
GoalAction after successful validation; decision history stays readable.

- move duration is 0.2..2s in both API and local contract.
- navigate_to/plan_path duration remains 0.2..10s; target requires exactly two numbers.
- non-movement tools require zero direct velocity.
- unused targets/skill requests require null.
- request_skill requires a nonempty description <=600 characters.
- No truncation, silent clamping, automatic retries or unchecked execution added.

Root anyOf/unsupported conditional schemas were avoided per the official
[structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs).
OpenAI Docs skill informed this schema design. Actual new-schema live access remains
unverified here because the agent environment has no API key.

## Errors and evidence

The former `transport_or_schema_error` catch-all is replaced with explicit stages:
api_timeout, api_transport_error, api_http_STATUS, response_json_error,
response_shape_error, api_incomplete_response, api_refusal,
response_ambiguous_output, action_json_error, action_schema_error, action_decode_error.

`failure_diagnostic.json` and result.error_diagnostic include safe metadata: HTTP
status, validated request/response IDs, response byte count/hash, token counts,
exception class, allowlisted API error codes and validation field locations/types.
Raw HTTP bodies, exception messages, credentials, validation input values, arbitrary
extra field names and response reasoning are not persisted. Hashes cannot reconstruct
the response; diagnostics intentionally prioritize data minimization.

On termination while a request is pending, `pending_call.json` records eventual
completion/failure/cancellation, available usage and a valid late action marked
executed=false. It is never executed after episode termination. Already-started
remote calls may still incur charges; local cancellation cannot undo them.

`terminal_state.json` records terminal qpos/qvel and contact body IDs/names/distances,
including terminal steps that fall between ordinary 20Hz log samples.

## Video finalization

Installed imageio writer context managers skip close on exception. Both runners now
close the video explicitly in finally before writing hashes. Otherwise ffmpeg could
finish after the manifest was written. Tested on GPU-injected policy failure: MP4
decoding and all artifact SHA256 checks pass after return. This fixes the discovered
failure-path mechanism; no old video or manifest was repaired or reclassified.

## Validation and remaining uncertainty

Schema parity tests cover every tool, cross-field arguments, bounds, transport errors,
refusal/incomplete/bad JSON, sanitization, single-request/no-retry behavior. GPU fault
injection and delayed-result tests exercise finalization and non-execution of late
actions; normal mock navigation regression also passes.

The original failed fourth response was not saved. Its exact cause remains unknown;
these corrections fix proven defects and make future errors distinguishable. Network
failures, API outages/limits and genuinely invalid outputs remain possible and fail
closed. No new paid API request was made during this fix.
