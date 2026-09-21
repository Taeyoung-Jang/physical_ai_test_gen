"""Offline arm IK isolation tests; no GPU inference or claimed robot success."""

from pathlib import Path

import mujoco
import numpy as np
import pytest

from clear_path.audit import initial_data, joint_table
from clear_path.contracts import Fixture
from clear_path.fixture import world_xml
from clear_path.push_probe import ArmGaitController


@pytest.fixture
def controller():
    p = Path(
        "/workspace/g1_failure/src/GR00T-WholeBodyControl/decoupled_wbc/sim2mujoco/resources/robots/g1/g1_gear_wbc.xml"
    )
    if not p.exists():
        pytest.skip("G1 assets unavailable")
    c = ArmGaitController.__new__(ArmGaitController)
    c.model = mujoco.MjModel.from_xml_string(world_xml(Fixture(), p))
    c.data = initial_data(c.model, p)
    c.scratch = mujoco.MjData(c.model)
    c.rows = joint_table(c.model)
    c.upper = c.rows[15:]
    c.upper_target = np.zeros(14)
    return c


def test_ik_only_changes_scratch_and_rate_limited_targets(controller):
    c = controller
    q, v, ctrl = c.data.qpos.copy(), c.data.qvel.copy(), c.data.ctrl.copy()
    targets = {
        s: c.data.site(f"{s}_push_site").xpos.copy() + [0.05, 0, -0.05] for s in ("left", "right")
    }
    c.arm_targets(targets)
    assert np.array_equal(c.data.qpos, q)
    assert np.array_equal(c.data.qvel, v)
    assert np.array_equal(c.data.ctrl, ctrl)
    assert np.max(np.abs(c.upper_target)) <= 0.040001
    assert np.isfinite(c.upper_target).all()
    assert not np.any(c.data.xfrc_applied) and not np.any(c.data.qfrc_applied)


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_bad_target_rejected(controller, bad):
    with pytest.raises(ValueError, match="finite"):
        controller.arm_targets({"left": np.array([bad, 0, 0]), "right": np.zeros(3)})


def test_missing_side_rejected(controller):
    with pytest.raises(ValueError, match="both"):
        controller.arm_targets({"left": np.zeros(3)})
