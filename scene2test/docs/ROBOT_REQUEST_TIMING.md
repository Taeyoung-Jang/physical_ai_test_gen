# Goal-agent configurable response wait

The former fixed 30s HTTP wait / 30s runner limit is superseded for
`tools/run_robot_goal_agent.py` by the following coordinated configuration:

```bash
uv run python tools/run_robot_goal_agent.py --live --model gpt-6-astra --enable-push --max-calls 10 --max-seconds 120 --response-timeout 90
```

`--response-timeout` is the HTTP read timeout in seconds, default 90, finite 1..300.
The runner's per-call wall deadline is automatically read timeout +30s (default 120).
HTTP connection/write/pool limits are respectively 10/10/5 seconds. The margin is
not a guarantee that every combination of network phases finishes within the runner
deadline; HTTP read limits apply per operation, while the runner bounds total waiting
before it stops advancing physics and rejects a late action. Cleanup still joins an
in-flight request; this is not a hard process-exit deadline or remote cancellation.

`--max-seconds 120` remains a separate simulation-time budget and includes inference
waits. It can end an episode before the API deadline. A long response can also be
rejected by the existing pose-freshness guard. No simulation freeze, extra calls,
automatic retry, or silent increase of the experiment's simulation budget is added.
Ten calls is an upper bound, not a guarantee of completing ten decisions in 120s.

The default increased wait applies to the goal agent, with or without pushing.
Direct API calls/legacy velocity runner retain 30s read wait unless given a Journal
with an explicit read setting. Shared transport connect/write/pool limits now use
10/10/5s. Protocol and API journals retain actual configured limits and measured times.
CLI prints these before launch. Timing source is included in protocol hashes.

`failed_transport_event` now preserves the failure phase even when subsequent
connection cleanup overwrites `last_transport_event`. Existing exception chains,
request IDs, primary deadline and pending-call artifacts remain intact. Request-ID
diagnostics follow the official guidance at https://developers.openai.com/api/reference/overview .

Validation uses mock HTTP transport (timeout propagation, exact failure phase, no
retry, malformed setting rejection) and a real GPU run with a mock policy sleeping
32 wall seconds before replying. This verifies the local 30s cutoff is removed,
not that provider latency, schema acceptance or live autonomous task success is solved.
