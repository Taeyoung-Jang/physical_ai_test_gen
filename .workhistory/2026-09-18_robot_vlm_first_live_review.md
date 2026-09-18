# First live robot VLM run: artifact review

User requested explanation of BUDGET_EXHAUSTED, not a new run or code change.
Reviewed `/workspace/g1_failure/runtime/robot_vlm/20260918T140520_061590Z`.

Actual OpenAI model reported gpt-6-astra. Two calls, two accepted actions:
1. Body-frame vx=0.28m/s, vy=0.008m/s, yaw_rate=0.01rad/s for 2s.
   Response latency 9.206676s; input/output tokens 2283/176.
2. vx=vy=0, yaw_rate=0.18rad/s for 1s.
   Response latency 6.236461s; input/output tokens 2282/141.

max_calls=2 was exhausted; max_simulation_s=60 was not reached. Recorded simulation
duration 18.845s includes settling, inference-wait gait, and action execution.
valid_execution=true, success=false, final goal distance 5.5612375m.
CUDAExecutionProvider; actual API calls and actions, not MockPolicy.
No goal-reaching, obstacle removal, vision-only reasoning or general autonomy claim.
Both camera and full GT geometry/pose were policy inputs; modality contribution is
not isolated. Observation/action records distinguish commands from physical outcomes.

The uv hardlink warning was nonfatal: installation used a full-copy fallback.
No additional paid requests, API-key reads or controller modifications performed.
This establishes live connection/action-loop evidence, not task success.
