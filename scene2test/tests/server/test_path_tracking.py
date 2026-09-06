import numpy as np
import pytest

from simulation_server.path_tracking import contact_slip_speeds, path_errors, supervised_command


def test_path_frame_and_wrapped_heading():
    cross, heading = path_errors([0, 1, 0], [1, 0, 0, 0], [0, 0, 0], 0)
    assert cross == 1
    assert heading == 0
    assert supervised_command([0.3, 0, 0], cross, heading)[2] < 0
    assert abs(supervised_command([0.3, 0, 0], 100, 100)[2]) <= 0.5


def test_rolling_contact_is_not_ankle_slip():
    mujoco = pytest.importorskip("mujoco")
    model = mujoco.MjModel.from_xml_string('''<mujoco><worldbody>
      <geom type="plane" size="5 5 .1"/>
      <body name="left_ankle_roll_link" pos="0 0 .099">
        <freejoint/><geom type="sphere" size=".1" mass="1"/>
      </body></worldbody></mujoco>''')
    data = mujoco.MjData(model)
    data.qvel[4] = 1.0
    mujoco.mj_forward(model, data)
    point = data.contact[0].pos
    data.qvel[0] = data.qpos[2] - point[2]
    mujoco.mj_forward(model, data)
    assert data.qvel[0] > 0.09  # The ankle is moving, but the contact point is stationary.
    assert max(contact_slip_speeds(model, data)) < 1e-10
    data.qvel[0] += 0.2
    mujoco.mj_forward(model, data)
    assert np.allclose(contact_slip_speeds(model, data), 0.2)
