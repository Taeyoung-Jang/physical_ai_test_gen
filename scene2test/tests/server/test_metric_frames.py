import numpy as np
import pytest

from simulation_server.worker import LocomotionMetrics


def test_free_joint_angular_velocity_is_already_local():
    mj = pytest.importorskip("mujoco")
    model = mj.MjModel.from_xml_string('''<mujoco><worldbody>
      <body pos="0 0 2"><freejoint/><geom type="sphere" size=".1"/>
        <body><joint name="j"/><geom type="sphere" size=".05"/></body>
      </body></worldbody><actuator><motor joint="j"/></actuator></mujoco>''')
    data = mj.MjData(model)
    data.qpos[3:7] = [np.cos(.4), 0, np.sin(.4), 0]
    data.qvel[5] = .7
    data.time = 2
    mj.mj_forward(model, data)
    velocity = np.zeros(6)
    mj.mj_objectVelocity(model, data, mj.mjtObj.mjOBJ_BODY, 1, velocity, 1)
    metrics = LocomotionMetrics(np.array([0, 0, .7]), model.opt.timestep)
    metrics.update(model, data)
    assert metrics.result()["mean_yaw_rate_radps"] == pytest.approx(velocity[2])
    assert metrics.result()["yaw_rate_rmse_radps"] == pytest.approx(0)
