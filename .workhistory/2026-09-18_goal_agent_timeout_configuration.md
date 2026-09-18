# Coordinated goal-agent response timing fix

User requested remediation of the first-call 30s timeout. Preserved all prior changes
and run evidence; no paid calls, model substitution, retries or changes to task strategy.

## Changes

- New immutable RequestTiming: HTTP read default90s, finite range1..300; runner's
  response deadline derived as read+30s (default120s).
- Goal-agent CLI `--response-timeout` passes through runner -> per-call Journal ->
  worker ContextVar -> shared HTTP transport. Protocol and startup console print both
  limits and the separate simulation budget. Added timing-source hash.
- Shared HTTP transport uses explicit connect/write/pool10/10/5s. Direct calls and
  legacy velocity journal retain30s read default unless explicitly overridden.
- Preserve `failed_transport_event` separately from cleanup's last_transport_event.
  Exception chains, request IDs, pending-call outcome, late-action rejection and
  no-retry behavior remain unchanged.
- No physics pause. Inference still consumes --max-seconds simulation budget; a
  simulation budget or freshness guard may terminate/reject before response deadline.
- Worker cleanup still waits for an in-flight operation; runner deadline is not an
  absolute process-exit/cancellation guarantee. Per-operation read timeout differs
  from end-to-end wall time. Increased wait is mitigation, not proof of remote fix.

OpenAI Docs skill used; official request-debugging overview consulted, request-ID
diagnostics retained. New docs ROBOT_REQUEST_TIMING.md, update notices in existing
debugging and push-integration docs supersede historical30s defaults.

## Verification

90 unit/regression tests passed,5 explicitly gated GPU tests skipped (5.76s).
Ruff and git diff --check passed. CLI rejects NaN timeout before creating run output.
Mock HTTP test verifies actual request timeout fields, failed receive phase preserved
through cleanup, and exactly one request without retries.

GPU test with push-enabled controller and mock policy delayed32 wall seconds:
`/workspace/g1_failure/runtime/robot_timeout_checks/20260918T173805_236808Z`.
1 test passed (71.40s including setup/artifact generation). Action accepted after
32.038s, POLICY_STOP, valid=true, API calls0. Simulation ended31.675s. All14 manifest
artifacts verify. This validates local >30s response handling, not live API success
or robot task completion. No original experiments overwritten.
