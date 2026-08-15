# g1-local-nav — agent notes

Full spec: `../.blueprint/g1_local_hierarchical_vla_development_blueprint.md`. Read it before making
architectural changes — this file only summarizes the rules that matter turn to turn.

## What this is

A **hierarchical** vision-language-to-locomotion system, not an end-to-end VLA. Never call
SmolVLM2 itself "the VLA" in docs, comments, or output — it only picks one of four discrete
navigation actions. The actual walking/balancing is a separate pretrained controller
(`GrootLocomotionController`, NVIDIA GR00T Balance/Walk ONNX) that this project does not train.

Task: "Move toward the red box and stop near it." Nothing else is in scope for v1 (see blueprint
§4.2) — no arm manipulation, no fine-tuning, no real hardware, no CUDA, no multi-room nav.

## Isolation from the parent workspace

This directory is deliberately **not** connected to `../scene2test/`. Different simulator
(MuJoCo, not PyBullet), different robot (Unitree G1, not Franka/laikago), different goal
(navigation demo, not failure-search test generation). Do not import from `../scene2test/src`
or try to unify the two — that was an explicit, considered decision, not an oversight.

## Environment

Two separate Python environments, not one:
- `g1-sim` — LeRobot + MuJoCo + ONNX Runtime + Unitree SDK. Blueprint recommends conda for
  `pinocchio`; check `envs/SETUP_NOTES.md` for what was actually used on this machine (plain
  venv was tried first since conda/miniforge is not installed here — don't assume conda exists).
- `g1-vlm` — mlx-vlm + FastAPI, talks to `g1-sim` over local HTTP, never imports simulator code.

Never install into the system/base Python. Always activate the right venv first.

## Order of operations (blueprint §20–21, do not skip ahead)

1. `scripts/verify_platform.py` must pass before writing application code.
2. The **upstream** LeRobot G1 + MuJoCo + GrootLocomotionController path must be smoke-tested
   manually before any of this project's own code touches the robot. If it fails, diagnose
   whether it's a DDS/CycloneDDS problem, a MuJoCo problem, or an ONNX problem — don't guess.
   If it's confirmed a Darwin DDS incompatibility, switch to the fallback track (blueprint §19.1)
   explicitly and document that switch; don't silently patch around it.
3. Every milestone in the blueprint has its own acceptance criteria. Don't mark one done without
   running its actual completion check.

## Hard rules

- Never claim something "works" without having actually run it on this Mac. If a step can't be
  verified in the current environment, say so plainly instead of documenting an assumed success.
- All failure modes (VLM timeout, invalid output, camera stale, NaN command, excessive roll/pitch)
  resolve to STOP. No infinite retries.
- Don't edit anything inside the Hugging Face cache or `site-packages`. Scene/config customization
  goes through this repo's own adapter layers.
- Pin upstream commit SHAs and model revisions once the first successful run happens — don't track
  upstream `main` indefinitely.
- `runs/`, downloaded ONNX/VLM weights, and `third_party/` clones are gitignored — never commit them.
