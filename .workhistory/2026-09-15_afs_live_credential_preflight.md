# AFS live ValueError investigation and credential preflight

Date: 2026-09-15 UTC. User requested remediation of the first live command failure.
Run: `/workspace/g1_failure/runtime/llm_afs_expanded/20260915T135227_075396Z`.

## Evidence and diagnostic boundary

The directory contains config/context/protocol/request/status, but no api_response,
raw_proposal or suite. Status records only ValueError. Current provider explicitly
raises ValueError for missing OPENAI_API_KEY; non-200 HTTP errors use RuntimeError
and invalid JSON normally uses JSONDecodeError. Missing credential delivery is the
leading explanation, not a conclusively recovered exception message. Other pre-response
ValueError paths cannot be excluded with these records. The assistant's environment
does not establish the state of the user's earlier terminal. No key values were read
out or persisted. Original artifacts remain unchanged.

The uv hardlink warning reports fallback to copy and successful installation; it does
not explain this Python exception. OpenAI Docs skill consulted and official quickstart
opened: https://developers.openai.com/api/docs/quickstart. Environment-variable guidance
does not imply authentication or account model access has been verified.

## Changes and tool constraint

Tried a minimal existing CLI preflight patch via apply_patch, then approved escalated
apply_patch. Both failed reading the existing file due to bwrap namespace permission.
Did not replace the committed file wholesale or alter container security settings.

Added `scene2test/tools/run_expanded_afs_checked.py` instead. It delegates unchanged
arguments to the original CLI after checking live key presence and whitespace/control/
non-ASCII errors. `--check-only` is a local-only check, with no network, artifacts or
robot execution. It never prints key values. Original CLI error reporting remains
unchanged; this is an additive preflight mitigation, not a repair of every error path.

Added `tests/test_afs_credential_preflight.py`: 12 tests passed in 0.72 seconds.
Ruff check passed. Tests use dummy strings and mocked delegation, no real API calls.
The two preexisting untracked method-documentation files were preserved.

## User next step (same RunPod terminal)

```bash
read -rsp "OpenAI API key: " OPENAI_API_KEY
export OPENAI_API_KEY
echo
uv run python tools/run_expanded_afs_checked.py --check-only
```

KEY_PRESENT means only that Python sees a syntactically plausible nonempty credential,
not successful authentication. If ready to make a paid call, run:

```bash
uv run python tools/run_expanded_afs_checked.py --live --samples 4 --seed 17
```

This launches at most the existing single API call and scene generation, not a GPU
rollout. If another failure occurs, preserve and inspect the new run directory; never
send the secret to chat. No paid retry was made during this remediation.
