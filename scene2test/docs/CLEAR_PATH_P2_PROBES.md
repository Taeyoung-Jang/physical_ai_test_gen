# P2: actual-contact unit probes (2026-09-15)

Status: partial. CUDA arm-reach passed; hand/box contact and small physical box
displacement observed. Forward push success threshold is NOT met. No complete
clear-path task, side-bay placement, autonomous approach, release, or traversal
is validated. No GPT/API calls are made by these tools.

## Run

From `scene2test` with the existing GPU environment and GR00T assets:

```bash
uv run python tools/run_clear_path_probe.py --kind arm_reach
uv run python tools/run_clear_path_probe.py --kind push_contact
uv run python tools/render_clear_path_probe.py /absolute/path/to/probe/run
```

Default outputs: `/workspace/g1_failure/runtime/clear_path_probes/<UTC>/`.
Each probe preserves scene XML, robot audit, source hashes, initial state, commands,
joint states, contacts, result, HTML report, real-rollout MP4/GIF and manifest.
The replay command creates a new `overhead_replay` directory and refuses overwrite.
Replay uses recorded 20 Hz states, not new physics; original files are unchanged.
Videos label actual execution versus recorded replay. Render timing is approximate
20 Hz for replay (recorded timestamps remain authoritative).

## Controller and measurements

The original lower-body Walk.onnx runs on CUDA. An isolated subclass adds
position-only damped Jacobian IK on scratch state for both palms, with bounded
upper-joint targets, PD plus bias compensation and joint actuator-force clamps.
Only actuators advance the live simulation: no live object teleportation, injected
external force, or attachment constraint. GT pose base-hold is an additional
controller condition, not the unmodified GR00T baseline.

Arm reach uses the original x=1 spawn. Push probes explicitly initialize at x=3.2
before any simulation step, near the unchanged 2 kg box. This is not navigation.
Current v4 palm targets are base+[0.26, +/-0.20, -0.05] meters. Settle 0-2 s,
reach 2-5 s, forward command 0.18 m/s during 5-9 s, hold thereafter.
The 4..20 s CLI duration is a hard execution cap, not an extension of the push phase.
Default durations: arm 8 s, push 11 s. Joint-target rate limit: 0.8 rad/s.

Stop guards: robot/world forbidden contact, hand contact normal force above
120 N per contact, low pelvis or excessive tilt, numerical/nonfinite state,
unexpected external force. Foot/floor contact is allowed; palm/box is allowed
only during reach/push/hold. Robot self-collision classification is NOT implemented.
Per-contact normal force is not the sum of hand forces or net box force.

Arm success requires final maximum palm error <8 cm. Push success requires
positive-x box displacement >8 cm with hand contact. Both require valid execution,
no fall/forbidden contact and normal duration completion. `clear_path_success`
remains null: a unit-probe pass is not task completion. A completed failed probe
returns CLI exit 0; consult `result.json` for `probe_success`.

## Evidence and next step

Five local tuning probes, not independent statistical replications:

| Condition | Kind | Result | Measurement |
|---|---|---|---|
| v1 | arm reach | fail | final error 12.24 cm |
| v2 | arm reach | pass | final error 4.47 cm |
| v2 | push | fail | no hand contact |
| v3 | push | fail | +1.27 cm box x, peak contact 17.08 N |
| v4 | push | fail | +3.16 cm box x, peak contact 21.33 N |

All five completed on CUDA without detected fall or forbidden robot/world contact.
The original push target had ~21 cm scratch IK residual; a nearer/higher target
reduced residual to ~2 cm and enabled real contact. Increasing forward command
increased displacement, but does not establish a robust pushing strategy.

Next: implement and test contact-maintaining push/retract control with bounded
force monitoring and repeated initial conditions. Then side-bay placement, map
update and traversal; only after a physical skill passes should GPT choose it.
Do not relax the 8 cm criterion, lighten the fixture silently, or expose an
unvalidated physical action to the planner as executable.
