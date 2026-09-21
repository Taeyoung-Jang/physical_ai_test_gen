import inspect
import math

import pytest

from robot_vlm.budget import simulation_limit
from robot_vlm.goal_runner import run


def test_default_is_unlimited():
    assert inspect.signature(run).parameters["max_seconds"].default is None
    assert math.isinf(simulation_limit(None))
    assert 1000000 < simulation_limit(None)


@pytest.mark.parametrize("seconds", [3, 120, 121, 600, 3600])
def test_explicit_limit_has_no_120s_ceiling(seconds):
    assert simulation_limit(seconds) == seconds


@pytest.mark.parametrize("seconds", [-1, 0, 2, float("nan"), float("inf")])
def test_invalid_explicit_limit(seconds):
    with pytest.raises(ValueError):
        simulation_limit(seconds)
