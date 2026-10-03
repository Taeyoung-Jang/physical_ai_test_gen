# Behavior AFS missing context hash — 2026-09-26

User's live run: runtime/behavior_afs/20260926T120758_764897Z.
Response status completed; host rejected proposal with stale proposal context.
Root cause: request contained context but neither supplied its computed digest nor
constrained the response digest. Model invented a different digest. This was our
request-construction bug, not missing credentials or a stale robot observation.

Added behavior_request.request: host-computed digest in request envelope and
singleton enum in JSON schema; explicit copy-not-compute instruction. Existing
host stale-context validation is preserved for live and imported proposals.
OpenAI Docs Structured Outputs enum guidance informed the schema constraint.

Explicit --recover-run accepts only legacy requests lacking supplied digest,
with rebuilt verified context equal to saved context and request payload, and
stored proposal equal to completed response content. Binds only the metadata;
spaces are unchanged and all normal semantic constraints remain enforced.
Recovery writes a separate audit and new output, never alters the original run.
This is trusted-local correspondence, not authentication against malicious writers.

Recovered without API/GPU calls:
/workspace/g1_failure/runtime/behavior_afs/20260926T121235_780634Z
ready=7, origin=recovered_openai_response.
LLM spaces: mass 1.0/2.2 kg and floor friction 0.6/1.0, plus control and exploration.
No new robot failures claimed; no robot ran during this fix.

Tests: 18 passed in 9.95s (behavior request, core, CLI/physics parameter tests).
Covers request enum/envelope, preserving original proposal, mismatch rejection
for current context, saved request and saved proposal. Ruff passed.
Execution command document updated with recovered output path and recovery command.
No commit/push performed.
