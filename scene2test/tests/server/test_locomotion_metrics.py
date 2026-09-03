from __future__ import annotations

import math

import numpy as np

from simulation_server.worker import _quaternion_rpy


def test_quaternion_rpy_identity() -> None:
    assert _quaternion_rpy(np.asarray([1.0, 0.0, 0.0, 0.0])) == (0.0, 0.0, 0.0)


def test_quaternion_rpy_yaw() -> None:
    angle = math.pi / 2
    quaternion = np.asarray([math.cos(angle / 2), 0.0, 0.0, math.sin(angle / 2)])

    roll, pitch, yaw = _quaternion_rpy(quaternion)

    assert math.isclose(roll, 0.0, abs_tol=1e-12)
    assert math.isclose(pitch, 0.0, abs_tol=1e-12)
    assert math.isclose(yaw, angle, abs_tol=1e-12)
