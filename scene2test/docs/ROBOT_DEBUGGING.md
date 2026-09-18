# Robot goal-agent diagnostics

The normal `tools/run_robot_goal_agent.py` command now enables per-call diagnostics automatically. No debug flag or new API key setting is required. This change does not raise timeouts, retry requests, change GPT decisions or alter the scene.

## Files in each new run

- `api_call_000.jsonl`, `api_call_001.jsonl`, ...: flushed UTC events with elapsed wall seconds, observation version and a unique client request ID. Includes policy/API start, HTTP transport phase events (TCP/TLS/send/receive when emitted by HTTPX), response headers, completion and failures.
- `runner_deadline.json`: runner's deadline, measured wall wait, simulation time and client request ID. Created immediately before terminating for a response deadline.
- `failure_diagnostic.json`: primary categorized failure.
- `pending_call.json`: outcome of an outstanding call after the robot loop stopped; never executed.
- `unexpected_error.json` / CLI `error.json`: unexpected exception chain and stack locations.
- Existing observations, camera images, decisions, video and manifest remain available.

The shared API transport also adds elapsed time, exception chain, HTTP error message/parameter and client request ID to diagnostics for the older velocity policy. The new per-call journal is wired into the goal-agent runner.

## Reading the trace

```bash
tail -f /workspace/g1_failure/runtime/robot_goal_agent/<run>/api_call_001.jsonl
```

Look at the last transport event before `api_failed`. For example, completion of request body sending followed by response-header waiting and ReadTimeout narrows the delay to waiting for a response; it does NOT by itself prove server-side inference was the cause. A failed TCP/TLS phase indicates an earlier transport problem. Mock transports may not emit real transport events.

The runner's 30-second wall deadline and HTTPX's 30-second per-operation timeout remain separate from `--max-seconds`, which is simulation time. Cleanup can wait for an in-flight operation after simulation stops. Match the client request ID across runner, journal and pending-call records; a server request ID exists only if response headers were received.

OpenAI's official request-debugging guidance recommends request IDs and supports a client-generated ID, including for requests where no server response was received: https://developers.openai.com/api/reference/overview

## Privacy and limits

No Authorization headers, environment dump, request image/base64, full request payload or stack locals are logged. Exception chains preserve redacted messages and file/line/function locations. HTTP API error messages and invalid action text excerpts are capped at 2,000 characters and redact the configured API key, sk-prefixed tokens and Bearer credentials. These excerpts may contain application context: review logs before sharing publicly. No full raw provider response or hidden reasoning is persisted. Logs flush on each event but are not fsync crash-durable. Diagnostics cannot retroactively reconstruct old runs or guarantee identification of remote-server causes.
