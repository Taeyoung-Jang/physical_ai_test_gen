# Robot VLM call budget and architecture explanation

User requested raising the call budget to ten and explaining the robot instructions
and how representative this pipeline is of robotics systems.

Changed only default max_calls 4→10 in tools/run_robot_vlm.py and robot_vlm/runner.py,
and the corresponding documentation. Existing CLI overrides remain valid. Hard
validation range remains 1..20. Simulation default remains 30s (independent budget);
recommend explicitly passing --max-seconds 120 for a longer ten-call trial. Ten is
a maximum, not a guarantee: policy stop, physical failure, time or API errors may
end earlier. No new paid request or robot rollout performed.

Working tree contained untracked implementation from earlier turns. Preserved all
other contents. Update File (including escalated CLI apply_patch) still failed on
bwrap. Read existing files and replaced only asserted exact default strings using
apply_patch Add File; did not discard other work. Historical protocols/results remain
unchanged and retain original source hashes/defaults.

Actual instruction: reach goal_xy_m without falling or contacting obstacles. Inputs
are robot RGB, full geometry map, GT pose, goal and previous execution status. GPT
selects body velocity/duration; no reference route, manipulation or path planner.
GR00T Walk.onnx converts command plus proprioception into joint targets; PD applies
actuator controls in MuJoCo. This is a hierarchical research configuration, NOT a
claim that most robots use cloud VLM velocity selection or GPT motor control.

Primary sources reviewed for architecture comparison:
- https://docs.nav2.org/rolling/getting_started/navigation_concepts/navigation_servers/
  (planner/controller separation and conventional navigation roles)
- https://robotics-transformer2.github.io/
  (learned vision-language-action alternative)

An internal robot planner is not external test-system intervention if fixed and
declared as part of the robot under test. Do not secretly add goal routes or tune
the robot after each AFS failure. Current raw-VLM velocity baseline omits continuous
local avoidance and full history/planning machinery, so failures characterize this
specific stack rather than all G1 robots or all VLM robot systems.
