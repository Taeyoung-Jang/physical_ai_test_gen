# Environment setup notes — what actually happened on this machine

This deviates from the blueprint's conda-first recommendation in a few places. Recorded here so
nobody re-derives this from scratch or assumes conda exists.

## `action_duration_s: 0.30` (configs/app.yaml default) likely too short to see movement

Milestone 5's fake-VLM closed-loop run (ep_fake_004, 80 steps, `SDL_VIDEODRIVER=dummy`,
`--settle-s 8`) showed real, changing roll/pitch (±0.06-0.08 rad, safety threshold not
tripped) but the head-camera view barely differed between step 0 and step 79 — the robot
wasn't visibly translating. This matches what Milestone 2 already found: scripts/
run_scripted_motion.py's original 1.0s FORWARD hold produced almost no displacement, and had
to be widened to 5.0s before the gait visibly covered ground (see that script's SEQUENCE
comment). The blueprint's own suggested default (§15) is 0.30s per chunked action; that may
simply be too short for this particular locomotion controller's gait to develop within one
chunk. Not a bug — a tuning gap, flagged here rather than silently left. If a future episode
needs to visibly cover distance (e.g., Milestone 6's red-box approach), try increasing
`control.action_duration_s` first before suspecting the control loop.

## Safety-critical bug: `obs["imu.rpy.*"]` is broken in simulation mode

`UnitreeG1.get_observation()`'s `imu.rpy.roll`/`.pitch`/`.yaw` fields come from the sim bridge's
own rpy computation, which is stuck at exactly `0.0` for roll regardless of actual robot
orientation — confirmed via `scripts/diag_imu.py`: `imu.quat.*` visibly changed across 10 reads
(real rotation happening, including the robot toppling over in one test) while `imu.rpy.roll`
stayed `0.0` every single time. This matters because `safety.check_frame_safety()` uses
roll/pitch to detect the robot tipping over and force a STOP — a stuck 0.0 means that check
silently never fires.

**Fix (`src/g1_local_nav/robot_runtime.py`, `G1Runtime.latest_frame()`):** roll/pitch/yaw are
computed from `obs["imu.quat.*"]` via `scipy.spatial.transform.Rotation`, not read from
`imu.rpy.*` at all. `G1Runtime` is the only place that should ever read orientation — don't
add a second `obs["imu.rpy.roll"]` read elsewhere in this codebase without this same fix.

## Known benign noise

## Machine

- `arm64` native (not Rosetta) — confirmed via `platform.machine()` and `arch`.
- No conda/mamba/micromamba installed. Did not install Miniforge — used plain `venv` instead,
  which turned out to be sufficient (see below). If a future dependency genuinely requires conda,
  install Miniforge with a **custom prefix and skip `conda init`** so it doesn't rewrite shell rc
  files; this project should stay opt-in.
- System `python3` (`/Library/Frameworks/Python.framework/.../python3`, 3.10.11) was not used.
  `/usr/local/bin/python3.11` (python.org universal2 installer) was used for the `g1-vlm` venv.
  **`g1-sim` needs Python 3.12 specifically** — LeRobot's `pyproject.toml` hard-requires
  `>=3.12` (not just "recommended" as the blueprint implies). Installed via
  `brew install python@3.12` → `/opt/homebrew/bin/python3.12`.

## `pinocchio` — a real gotcha

`pip install pinocchio` installs the **wrong package** — PyPI's `pinocchio` (0.4.3) is a nose
testing-framework plugin, unrelated to the Pinocchio robotics library. The real one is published
as **`pin`**: `pip install pin`. It pulls prebuilt `cmeel-*` wheels (boost, eigenpy, coal, etc.)
with real arm64 macOS binaries — no conda-forge needed. Verified with an actual
`buildSampleModelHumanoidRandom()` + `forwardKinematics()` call, not just a bare import.

## `cyclonedds` / `unitree_sdk2py` — needs the C library built first

`unitree_sdk2py==1.0.1` pins `cyclonedds==0.10.2` (the Python binding), which needs the native
CycloneDDS C library present at build time — Homebrew has no formula for it, so it's built from
source:

```bash
git clone --branch releases/0.10.x --depth 1 \
  https://github.com/eclipse-cyclonedds/cyclonedds.git third_party/cyclonedds-c
cd third_party/cyclonedds-c
mkdir build install && cd build
cmake -DCMAKE_INSTALL_PREFIX=../install -DBUILD_EXAMPLES=OFF -DBUILD_TESTING=OFF ..
cmake --build . --target install -- -j$(sysctl -n hw.ncpu)
```

Then `CYCLONEDDS_HOME` must be set **every time** before pip-installing or importing
`unitree_sdk2py`/`cyclonedds` in `g1-sim`:

```bash
export CYCLONEDDS_HOME="$(pwd)/third_party/cyclonedds-c/install"
```

(`cmake` itself wasn't installed either — `brew install cmake` first.)

Verified with a real `DomainParticipant()` instantiation, not just an import — this is the exact
thing the blueprint flagged as unverified on Darwin (§3, §19.1), and it works.

## What's confirmed working (Milestone 0, `scripts/verify_platform.py`, exit 0 both venvs)

- `g1-sim`: arm64, MuJoCo (real physics step), onnxruntime (CoreMLExecutionProvider available),
  CycloneDDS `DomainParticipant`, `lerobot.robots.unitree_g1.{unitree_g1,gr00t_locomotion}` imports.
- `g1-vlm`: arm64, MLX with `Device(gpu, 0)` (Metal confirmed, not CPU fallback).

## Recreating the environments

```bash
# g1-sim
/opt/homebrew/bin/python3.12 -m venv envs/.venv-g1-sim
source envs/.venv-g1-sim/bin/activate
pip install pin mujoco loguru msgpack msgpack-numpy opencv-python pyzmq pyyaml httpx pydantic typer rich onnxruntime
export CYCLONEDDS_HOME="$(pwd)/third_party/cyclonedds-c/install"   # after building it, see above
pip install -e third_party/unitree_sdk2_python
pip install -e 'third_party/lerobot[unitree_g1]'
pip install 'lerobot[viz]'         # rerun-sdk — needed for --display_data=true
pip install 'lerobot[pynput-dep]'  # pynput — needed for --teleop.type=keyboard
# Neither viz nor pynput-dep is pulled in by [unitree_g1] — both had to be added separately.
# pynput's macOS keyboard listener needs Accessibility permission granted to the terminal app
# (System Settings > Privacy & Security > Accessibility) or key events silently don't register.

# g1-vlm
/usr/local/bin/python3.11 -m venv envs/.venv-g1-vlm
source envs/.venv-g1-vlm/bin/activate
pip install -U mlx-vlm fastapi 'uvicorn[standard]' pillow python-multipart pydantic orjson
```

`CYCLONEDDS_HOME` needs to be set in every new shell that touches `g1-sim` and imports
`unitree_sdk2py`/`cyclonedds` (not persisted automatically — add it to your shell profile or a
wrapper script if this gets tedious).

## `lerobot/unitree-g1-mujoco` — remote hub code has its own undeclared deps

`UnitreeG1.connect()` calls `make_env("lerobot/unitree-g1-mujoco", trust_remote_code=True)` —
this pulls `env.py` + a `sim/` package from the **Hugging Face Hub at runtime**, cached under
`~/.cache/huggingface/hub/models--lerobot--unitree-g1-mujoco/`. Its imports are not declared
anywhere in LeRobot's `pyproject.toml` (it's not LeRobot's own code), so missing ones only show
up as `ModuleNotFoundError` at actual runtime, one import at a time, unless you grep the cached
source first. Cross-referencing every `import`/`from` line in that cached snapshot against what
was already installed turned up exactly one real gap: `pip install scipy` (matplotlib and
termcolor were already present as transitive deps of other extras). `rclpy` (ROS2) also appears
but is behind what looks like a guarded/optional code path — do not install it, not needed here.

## `src/g1_local_nav` isn't pip-installed — `-m` invocation doesn't work

There's no `pyproject.toml`/`setup.py` making `g1_local_nav` an installed package, so
`mjpython -m g1_local_nav.cli` fails with `ModuleNotFoundError` (Python needs to already find
the module before any of its own `sys.path` bootstrap code runs). Run CLI/scripts by their file
path instead — `mjpython src/g1_local_nav/cli.py --policy fake` — which works because each
entry point inserts `src/` onto `sys.path` itself before importing sibling `g1_local_nav.*`
modules. `scripts/*.py` already followed this pattern; `cli.py` does too.

## Known benign noise

Every run prints a wall of `objc[...]: Class SDLApplication is implemented in both ... cv2/.dylibs/libSDL2 ... and ... pygame/.dylibs/libSDL2 ...` warnings. This is opencv-python and pygame
each bundling their own copy of libSDL2 — harmless duplicate-symbol warning, not a crash. Safe
to ignore / grep out.

## Not yet pinned

Upstream commit SHAs (`third_party/lerobot`, `third_party/unitree_sdk2_python`,
`third_party/cyclonedds-c`) and model revisions are **not pinned yet** per blueprint §7.1 ("최초
성공 후 모든 upstream commit SHA와 model revision을 고정한다") — do this after Milestone 1
(upstream smoke test) succeeds, not before, since we may still need to change branches/tags.
