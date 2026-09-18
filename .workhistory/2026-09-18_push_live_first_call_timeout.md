# Push-enabled live run: first-call response timeout

Reviewed `/workspace/g1_failure/runtime/robot_goal_agent/20260918T173003_900275Z`.
Analysis only: no code modifications, scene changes, retries or new paid calls.

One API call attempted, zero accepted actions, no skill files/executions. Result:
valid_execution=false, success=false, response_deadline at 30.0025 wall seconds.
Simulation stopped at 29.775 s while holding pose, base approximately
[0.95680,-0.01428,0.74187]. This does not evaluate the push executor's capability.

Per-call journal timeline, wall seconds since policy start:
- TCP connection starts .793, completes .848.
- TLS starts .854, completes .894.
- Request body transmission completes .929.
- Response-header receive starts .937.
- Runner deadline fires at ~30.003 (separate timing origin immediately before submit).
- Response-header receive fails at 30.975; connection cleanup completes 31.005.
- API failure persisted at 31.128, policy failure at 31.151.

Pending call ended in HTTPX/httpcore ReadTimeout: "The read operation timed out".
No response headers/status/server request ID were received. Cannot conclude API
authentication/schema acceptance, a provider 4xx/5xx, inference duration or provider
queue behavior from this run. Evidence establishes the wait failed after request send,
not during local action parsing or robot execution. The diagnostic's last_transport_event
is response_closed.complete because cleanup overwrites it; the journal and stack identify
the actual failed phase as receive_response_headers, not successful API completion.

Client request ID: c94021b2-054a-41ac-98c5-513704647ecd.
All 17 manifest artifacts pass hash verification. Full redacted exception stack retained.

Recommendation: expose and coordinate transport read timeout and runner response deadline,
and explicitly account for simulation time consumed during waits. Current 30s limits were
deliberately unchanged by logging/push integration; CLI max-seconds=120 does not override
them. Increased timeout may allow a response but is not proof of resolving remote latency.
Do not classify this as an AFS robot/physical failure or silently retry billable calls.
