# Robot API debug logging

User requested actionable retained errors, not silently masked failures or a timeout-only label.

Implemented default per-observation goal-agent journals with UTC/wall timings, UUID client request IDs sent as X-Client-Request-Id, HTTP transport phase events, response-header request IDs and status, terminal API events, redacted exception chains and stack locations. Preserve HTTP error message/parameter and invalid-action excerpts, not just broad error codes. Unexpected runner/CLI exceptions retain redacted stacks. Runner deadline writes its own measured record before cleanup; pending-call outcome remains separately preserved. CLI displays debug log location and distinguishes simulation budget from wall deadline.

No timeout, robot behavior, scene, retry policy or paid API call changes. Existing artifacts preserved. API key/authorization and stack locals excluded. Excerpts can contain application context; logs are not promised free of all sensitive domain data.

Used OpenAI Docs skill and official API overview debugging guidance for request-ID correlation. Implementation uses existing HTTPX trace extensions. File-update helper still encounters bwrap namespace failures; applied scoped complete Add File patches to the previously inspected untracked files, preserving their contents except intended edits.

Validation: unit/regression suite initially 60 passed, 2 GPU-only tests skipped; Ruff passed. Dedicated GPU fault/pending-call tests run separately without live API calls. See accompanying final verification in this work session. Documentation: scene2test/docs/ROBOT_DEBUGGING.md.
