"""Unit tests for G1Runtime's defensive privileged-state accessors (blueprint §14.3/§17
Milestone 6: ground-truth base position, lateral-offset spawn). These reach through several
layers of the vendored HF-hub sim module that only exist after a real connect() — which needs
mjpython + a MuJoCo GUI and can't run in pytest (see envs/SETUP_NOTES.md). What CAN run headless
is the "not connected yet" fallback path: every layer of the getattr chain is None, and these
methods must return None/False rather than raise.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from g1_local_nav.robot_runtime import G1Runtime


def test_base_xy_is_none_before_connect() -> None:
    runtime = G1Runtime()
    assert runtime._base_xy() is None


def test_set_lateral_offset_is_noop_before_connect() -> None:
    runtime = G1Runtime()
    assert runtime.set_lateral_offset(0.5) is False


def test_try_grasp_is_noop_before_connect() -> None:
    runtime = G1Runtime()
    assert runtime.try_grasp() is False


def test_release_grasp_is_noop_before_connect() -> None:
    runtime = G1Runtime()
    assert runtime.release_grasp() is False


def test_is_grasping_is_false_before_connect() -> None:
    runtime = G1Runtime()
    assert runtime.is_grasping() is False


def test_object_xyz_is_none_before_connect() -> None:
    runtime = G1Runtime()
    assert runtime.object_xyz() is None


def test_release_elastic_band_is_noop_before_connect() -> None:
    runtime = G1Runtime()
    # gradual_steps=0 so this doesn't block on time.sleep if the fallback ever regresses.
    assert runtime.release_elastic_band(gradual_steps=0) is False


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
