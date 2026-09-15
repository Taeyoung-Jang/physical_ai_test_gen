import mujoco
import numpy as np
import pytest

from clear_path import fixture
from clear_path import placement_preflight as preflight
from clear_path.contracts import Fixture
from scene_graph import SceneGraph


def test_north_push_rejected_without_global_impossibility_claim():
    check = preflight.direct_push_preflight(Fixture())
    assert check["south_gap_m"] == pytest.approx(0.25)
    assert check["required_footprint_width_m"] == pytest.approx(0.8)
    assert check["candidate_base_xy_m"][1] == pytest.approx(-0.83)
    assert check["decision"] == "REJECT_UNDER_CURRENT_APPROACH_MODEL"
    assert check["candidate_base_outside_corridor"]
    assert check["robot_execution_authorized"] is False


@pytest.mark.parametrize("xy", [fixture.BOX_START, fixture.BOX_TARGET, (4.09, 0.01)])
def test_map_matches_legacy_when_unrotated(xy):
    cfg = Fixture()
    nav = preflight.navigation_map(cfg, [xy[0] - 0.4, xy[0] + 0.4, xy[1] - 0.55, xy[1] + 0.55])
    old = fixture.navigation_map(cfg, xy)
    assert nav["blocked"] == old["blocked"]
    assert nav["reachable"] == old["reachable"]


def model():
    return mujoco.MjModel.from_xml_string(fixture.world_xml(Fixture()))


def test_rotated_snapshot_graph_map_share_measured_aabb_and_version():
    m = model()
    q = m.qpos0.copy()
    q[3:7] = [np.cos(np.pi / 8), 0, 0, np.sin(np.pi / 8)]
    before = q.copy()
    state = preflight.snapshot(m, q, Fixture(), state_version=1, source={"test": True})
    graph = SceneGraph.from_dict(state["scene_graph"])
    box = graph.get_object("clear_box")
    expected = (0.8 + 1.1) / np.sqrt(2)
    assert box.size[:2] == pytest.approx([expected, expected])
    assert graph.meta["state_digest"] == state["navigation_map"]["state_digest"]
    assert graph.meta["state_version"] == 1
    assert graph.meta["scene_revision"] == fixture.identity(Fixture())
    assert np.array_equal(q, before)
    assert state["navigation_map"]["reachable"] is False


def test_state_changes_do_not_change_fixture_revision():
    m = model()
    q = m.qpos0.copy()
    a = preflight.snapshot(m, q, Fixture(), state_version=0, source={})
    q[0] += 0.09
    b = preflight.snapshot(m, q, Fixture(), state_version=1, source={})
    assert a["navigation_map"]["scene_revision"] == b["navigation_map"]["scene_revision"]
    assert a["navigation_map"]["state_digest"] != b["navigation_map"]["state_digest"]
    assert b["navigation_map"]["reachable"] is False


def test_bad_state_and_drift_rejected():
    m = model()
    with pytest.raises(ValueError):
        preflight.snapshot(m, [float("nan")] * m.nq, Fixture(), state_version=0, source={})
    with pytest.raises(ValueError):
        preflight.snapshot(m, m.qpos0, Fixture(), state_version=-1, source={})
    m.geom("wall_south").pos[1] -= 1
    with pytest.raises(ValueError, match="geometry mismatch"):
        preflight.snapshot(m, m.qpos0, Fixture(), state_version=0, source={})


@pytest.mark.parametrize("bounds", [[1, 0, 0, 1], [0, 1, 2, 2], [0, 1, 2, np.nan]])
def test_bad_bounds_rejected(bounds):
    with pytest.raises(ValueError):
        preflight.navigation_map(Fixture(), bounds)
