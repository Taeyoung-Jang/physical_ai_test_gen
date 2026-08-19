# Provenance

Copied from Hugging Face Hub `lerobot/unitree-g1-mujoco`, per blueprint §14.2 ("upstream EnvHub
scene을 프로젝트의 assets/scenes/로 명시적으로 복제, 라이선스와 원본 revision 기록") — the
scene is not hand-edited in the HF cache; this is our own durable, version-pinned copy instead.

- Source: https://huggingface.co/lerobot/unitree-g1-mujoco
- Revision (sha): `a38dc8617f0fca51b38e9354dc58ee35ad850fb5`
- Last modified upstream: 2026-03-05T14:40:58Z
- Copied: 2026-08-16
- License: **none declared** — no `LICENSE` file, no README frontmatter license field, and the
  Hugging Face API's `cardData.license` is empty for this repo. The README states the sim is
  "adapted from gr00t_wbc" (NVIDIA GR00T-WholeBodyControl) but does not attribute a specific
  license for this derived repo. Flagging this explicitly rather than assuming a license that
  wasn't actually declared.

## What's here

Verbatim copy of the cached repo's `assets/` directory (robot XML/URDF + meshes, ~57MB). Not
modified. `scene_43dof.xml` here is the exact upstream file — the version with the red
navigation target added lives alongside it as `scene_43dof_with_target.xml` (see
`src/g1_local_nav/scene_adapter.py` for how it's generated/maintained).
