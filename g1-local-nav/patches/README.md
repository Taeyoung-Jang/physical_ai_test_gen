# Patches to `third_party/lerobot`

LeRobot is Apache 2.0 licensed (see `third_party/lerobot/LICENSE`). These are small, local,
documented patches applied to the editable clone — not a fork, not committed upstream. Re-apply
after re-cloning `third_party/lerobot` if it's ever recreated from scratch.

## `0001-macos-loopback-interface.patch`

**File:** `src/lerobot/robots/unitree_g1/unitree_g1.py`, `UnitreeG1.connect()`

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

**To reapply:**
```bash
cd third_party/lerobot
git apply ../../patches/0001-macos-loopback-interface.patch
```
