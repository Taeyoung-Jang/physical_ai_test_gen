# g1-local-nav

Apple Silicon, local-only, hierarchical vision-language-to-locomotion navigation for a simulated
Unitree G1 humanoid in MuJoCo. **This is not an end-to-end VLA.** A local MLX vision-language
model (SmolVLM2-500M) picks one of four discrete actions (`FORWARD`/`TURN_LEFT`/`TURN_RIGHT`/`STOP`)
from the head camera and a natural-language instruction; a separate pretrained locomotion
controller (NVIDIA GR00T Balance/Walk ONNX, via LeRobot's `GrootLocomotionController`) turns that
into actual balanced walking. Neither model is trained or fine-tuned in this project.

First and only demo task: **"Move toward the red box and stop near it."**

Full design spec: [`../.blueprint/g1_local_hierarchical_vla_development_blueprint.md`](../.blueprint/g1_local_hierarchical_vla_development_blueprint.md).
Agent-facing rules: [`AGENTS.md`](AGENTS.md).

Status: scaffolding + Milestone 0 (platform audit) in progress. See `runs/` for episode logs once
the closed loop exists — nothing runs end-to-end yet.

## Isolation

This directory is a separate project from `../scene2test/` in the same workspace — different
simulator (MuJoCo vs PyBullet), different robot, different goal (navigation, not failure-search
test generation). No code is shared between them.

## Setup

See `envs/SETUP_NOTES.md` for what actually installed on this machine (conda is not present here,
so the environment strategy deviates from the blueprint's conda-first recommendation where needed).
