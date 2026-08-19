# Patches to `third_party/lerobot`

LeRobot is Apache 2.0 licensed (see `third_party/lerobot/LICENSE`). These are small, local,
documented patches applied to the editable clone — not a fork, not committed upstream. Re-apply
after re-cloning `third_party/lerobot` if it's ever recreated from scratch.

## `0001-unitree-g1-connect-patches.patch`

Both patches below touch the same few lines of `UnitreeG1.connect()`
(`src/lerobot/robots/unitree_g1/unitree_g1.py`), so they're kept in one file rather than split
into 0001/0002 — splitting would just mean re-deriving an artificial line boundary through code
that's really one small `is_simulation` block.

### Part 1 — macOS loopback interface

**Problem:** In the `is_simulation=True` path, upstream hardcodes
`self._ChannelFactoryInitialize(0, "lo")` — Linux's loopback interface name. macOS's is `lo0`.
Confirmed via `ifconfig -l`. Without the patch, `lerobot-teleoperate --robot.type=unitree_g1
--robot.is_simulation=true ...` fails at `robot.connect()` with:

```
1786726266.749023 [0]   21053059: lo: does not match an available interface.
[ChannelFactory] create domain error. msg: Occurred upon initialisation of a cyclonedds.domain.Domain
Exception: channel factory init error.
```

This is exactly the Darwin DDS/loopback risk the design blueprint (§3, §19.1) called out in
advance — it manifested here, not as a `cyclonedds`/`unitree_sdk2py` build failure (those work
fine on this machine, see `envs/SETUP_NOTES.md`), but as this one hardcoded interface name.

**Fix:** `platform.system() == "Darwin"` branches to `"lo0"`, otherwise keeps `"lo"`. Minimal,
platform-conditional, doesn't change behavior on Linux.

### Part 2 — scene override hook (Milestone 6, red-box target)

**Problem:** `make_env("lerobot/unitree-g1-mujoco", trust_remote_code=True)` always loads the
scene XML path from the cached module's own `config.yaml` (`ROBOT_SCENE` field) via a hardcoded
file read — there's no kwarg to point it at a different scene. Blueprint §14.2 explicitly says
not to edit files inside the Hugging Face cache to work around this.

**Fix:** wraps the `make_env(...)` call in `g1_local_nav.scene_adapter.scene_override()` — a
context manager that temporarily monkeypatches `yaml.safe_load` (scoped to just that one call)
so the `ROBOT_SCENE` value it returns points at our own committed scene copy
(`assets/scenes/g1_hub/assets/scene_43dof_with_target.xml`) instead. No file on the cache is
ever written. Controlled by the `G1_LOCAL_NAV_SCENE` env var — unset means this whole thing is
a no-op and every Milestone 1-5 script keeps the exact upstream scene. The import is
best-effort (`try/except ImportError`) so plain `lerobot-teleoperate` usage without
`g1_local_nav` on `sys.path` still works unaffected.

**To reapply either/both:**
```bash
cd third_party/lerobot
git apply ../../patches/0001-unitree-g1-connect-patches.patch
```
