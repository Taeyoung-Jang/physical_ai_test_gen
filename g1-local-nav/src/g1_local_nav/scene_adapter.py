"""Injects the red-box navigation-target scene (blueprint §14, Milestone 6) without touching
the Hugging Face cache (blueprint §14.2: "Hugging Face cache 안의 config.yaml 또는 scene XML을
직접 편집하지 않는다").

The cached `lerobot/unitree-g1-mujoco` module's `make_env()` always reads `ROBOT_SCENE` from
its own `config.yaml` via a hardcoded `open()` + `yaml.safe_load()` — there is no kwarg to
override it. `scene_override()` scopes a temporary monkeypatch of `yaml.safe_load` to just the
duration of that one call, rewriting only the `ROBOT_SCENE` value in the dict it returns. No
file on disk is ever written; the patch reverts even on exception. The actual scene content
(with the target added) lives in this repo's own `assets/scenes/g1_hub/`, copied from the cache
per blueprint §14.2's recommended sequence — see that directory's NOTICE.md for provenance.
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path

import yaml

DEFAULT_TARGET_SCENE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "assets" / "scenes" / "g1_hub" / "assets" / "scene_43dof_with_target.xml"
)

SCENE_OVERRIDE_ENV_VAR = "G1_LOCAL_NAV_SCENE"


@contextlib.contextmanager
def scene_override():
    """No-op unless G1_LOCAL_NAV_SCENE is set — every existing Milestone 1-5 script/test that
    doesn't set it gets exactly the upstream default scene, unchanged. Set the env var to a
    scene XML path to use that scene, or to "1"/"" (any value) to use the default red-box
    target scene (DEFAULT_TARGET_SCENE_PATH).
    """
    raw = os.environ.get(SCENE_OVERRIDE_ENV_VAR)
    if raw is None:
        yield
        return

    target = Path(raw) if raw not in ("", "1") else DEFAULT_TARGET_SCENE_PATH
    if not target.exists():
        raise FileNotFoundError(
            f"{SCENE_OVERRIDE_ENV_VAR} points to a missing scene file: {target}"
        )

    original_safe_load = yaml.safe_load

    def _patched_safe_load(stream):
        result = original_safe_load(stream)
        if isinstance(result, dict) and "ROBOT_SCENE" in result:
            result = dict(result)
            result["ROBOT_SCENE"] = str(target)
        return result

    yaml.safe_load = _patched_safe_load
    try:
        yield
    finally:
        yaml.safe_load = original_safe_load
