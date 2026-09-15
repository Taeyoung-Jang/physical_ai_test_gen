import numpy as np
import pytest

from clear_path.contact_control import ContactControl


def observation():
    base = np.array([3.2, 0.0, 0.74])
    box = np.array([4.0, 0.0, 0.35])
    starts = {s: base + [0.24, y, 0.10] for s, y in (("left", 0.2), ("right", -0.2))}
    return base, box, starts


def test_phases_and_target_bounds():
    c = ContactControl()
    base, box, starts = observation()
    assert c.update(0, base, box, box, None) == ({}, 0.0)
    goals, vx = c.update(3, base, box, box, starts)
    assert c.phase == "reach" and vx == 0
    goals, vx = c.update(6, base, box, box, starts)
    assert c.phase == "push" and 0 < vx <= 0.22
    assert all(base[0] + 0.24 <= g[0] <= base[0] + 0.30 for g in goals.values())


def test_force_feedback_slows_and_stops_command():
    c = ContactControl()
    base, box, starts = observation()
    c.observe_contact(True, 60, 0.005)
    assert c.update(6, base, box, box, starts)[1] == pytest.approx(0.11)
    c.observe_contact(True, 90, 0.005)
    assert c.update(6, base, box, box, starts)[1] == 0


@pytest.mark.parametrize("time,advance", [(13.0, 0.0), (7.0, 0.13)])
def test_retract_and_release_are_measured(time, advance):
    c = ContactControl()
    base, box, starts = observation()
    moved = box + [advance, 0, 0]
    _, vx = c.update(time, base, moved, box, starts)
    assert c.phase == "retract" and vx < 0
    c.update(time + 2.1, base, moved, box, starts)
    assert c.phase == "released_hold"
    for _ in range(101):
        c.observe_contact(False, 0, 0.005)
    assert c.released
    c.observe_contact(True, 1, 0.005)
    assert not c.released


def test_invalid_observations_rejected():
    c = ContactControl()
    base, box, starts = observation()
    with pytest.raises(ValueError):
        c.update(float("nan"), base, box, box, starts)
    with pytest.raises(ValueError):
        c.observe_contact(False, -1, 0.005)
    with pytest.raises(ValueError):
        c.observe_contact(False, 1, 0)
