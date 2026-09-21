# Optional simulation time limit (2026-09-21)

The goal agent no longer has a mandatory/default 120-second simulation deadline.

```bash
uv run python tools/run_robot_goal_agent.py --live --model gpt-6-astra --max-calls 10 --enable-push --response-timeout 90
```

Omit `--max-seconds` for unlimited simulation time. To request a time limit, supply
any finite value >=3 seconds, including values greater than120. An explicit
`--max-seconds 120` STILL limits that run to120 seconds; remove it from old commands.

The call budget, per-call HTTP/runner response deadlines, policy stop, goal detection,
fall/contact/numerical guards and push duration bounds remain unchanged. This does
not mean infinite API calls or disabling safety termination. Longer episodes can
produce larger state logs/GIF/video and consume more compute. Physics still runs
during inference waits. There is no new simulation pause or automatic retry.

Protocol records `max_simulation_s: null` and `simulation_time_unlimited: true` when
unlimited, avoiding nonstandard Infinity JSON. The runner internally uses infinity
for comparisons only. Budget-source hash is recorded. No old artifacts are changed.
