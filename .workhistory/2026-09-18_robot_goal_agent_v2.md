# Goal-driven robot agent v2 implementation and GPU smoke

User requested broadening GPT decision-making and executing it, including robot-internal
planning/avoidance. Preserved v1 and prior failures; implemented a separate v2 robot
configuration without changing environment, external evaluator or AFS.

## Files added

- robot_vlm/goal_policy.py: GoalAction and goal-driven image policy, brief plan summary,
  recent 8-action/execution memory, navigate_to/plan_path/move/observe/stop/request_skill.
  Structured Responses output, high reasoning, 4096 output-token cap, explicit no-executor
  handling rather than advertising nonexistent manipulation. Mock policy clearly labeled.
- robot_vlm/navigation_tools.py: geometry-only robot-local BFS (5cm/0.4m radius),
  bounds/blocked endpoint/no-path feedback, world→body pose-hold and route follower.
- robot_vlm/goal_runner.py: separate runner derived from v1, internal route dispatch,
  measured tool feedback, per-step route following, GT base/yaw hold during inference.
  The copied runner is separate code: future common bug fixes need both versions reviewed.
- tools/run_robot_goal_agent.py: default 10 calls, 120 simulated seconds, mock default,
  --live required for paid calls, outputs under runtime/robot_goal_agent.
- tests/test_robot_goal_agent.py and docs/ROBOT_GOAL_AGENT.md.

Before writing checked git status; all preexisting untracked work retained. Only new
paths added, v1 source and saved artifacts untouched. No subagents used.

## Scope / safety / autonomy boundary

GPT chooses targets/strategy/action sequence; no external route or south-push instruction.
Planner uses robot-visible geometry only. AFS/evaluator information remains separate.
Unknown skill requests are returned as unsupported and do not move objects. No shell,
arbitrary code, grabbing or teleportation added. Physical actuator/contact limits remain.
Hold controller is a declared robot change, not hidden correction of a particular scene.
No claim of robust avoidance or full-body collision-free navigation: circular map and
gait tracker are approximations and terminal physical guards still apply.

## Verification

`pytest tests/test_robot_goal_agent.py tests/test_robot_vlm.py
tests/test_clear_path_contact.py -q`: 30 passed, 4.15s. New files Ruff check passed.
Tests cover reachable/blocked/outside routes, frame transforms and yaw wrap, bounded
follower, strict tool arguments/nonfinite data, history cap, multimodal HTTP request,
plan schema extraction, and expression of unsupported skill requests.

GPU run (not GPT):
`/workspace/g1_failure/runtime/robot_goal_agent/20260918T145642_563398Z`
Command: `.venv/bin/python tools/run_robot_goal_agent.py --max-calls 2 --max-seconds 10`.
CUDA policy, 2 mock decisions, zero API calls; valid_execution=true, success=false,
BUDGET_EXHAUSTED after 4.13s, final goal distance 5.73313m.
First mock navigate_to [1.35,0] reached within the declared 0.12m tolerance at
actual base [1.241239,-0.050073,0.745212]m; second query to [7,0] returned no_path.
Actual final base [1.266923,-0.023865,0.743916]m. All saved artifact hashes verified.
This proves tool/GPU wiring only; it does not demonstrate autonomous GPT planning.

## OpenAI / credential boundary

Used OpenAI Docs skill and fetched official structured-output documentation:
https://developers.openai.com/api/docs/guides/structured-outputs
No API-key helper available. Checked presence only: OPENAI_API_KEY absent in agent
environment. No key values or unrelated credential stores inspected. Thus no paid
live GPT calls; user can execute --live in their own configured terminal.

## Remaining

Live GPT goal planning/history/route requests unverified. Hold behavior not yet validated
with long live delays; latest GPU smoke only had immediate mock responses. No native
Responses function_call flow, generic robot backend, dynamic avoidance, manipulation,
full task success or AFS comparative result claimed. Native schema dispatch is explicit.
Current scene may be infeasible for available locomotion-only skills; preserve that as
a capability/environment finding instead of covertly changing geometry or solving it.
