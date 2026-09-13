import json

import pytest

from procedural_world.core import navigation_map, scene_graph
from procedural_world.navigation_stages import stage_world
from procedural_world.search import InvalidScene, SceneSearch, move_obstacle, outcome


def test_mutation_is_immutable_and_revision_consistent():
    base = stage_world("obstacle")
    original = base.to_dict()
    derived = move_obstacle(base, [1, 0.5])
    assert base.to_dict() == original
    assert derived.revision != base.revision
    assert derived.spawn_xy == base.spawn_xy and derived.goal_xy == base.goal_xy
    assert derived.boxes[:-1] == base.boxes[:-1]
    assert derived.boxes[-1].position == (9.1, 8.6, 0.5)
    assert navigation_map(derived)["scene_revision"] == derived.revision
    assert "obstacle_0" in json.dumps(scene_graph(derived).to_dict())


@pytest.mark.parametrize("offsets", [[0, 2.4], [3, 0], [float("nan"), 0], [0]])
def test_invalid_geometry_not_robot_failure(offsets):
    with pytest.raises(InvalidScene):
        move_obstacle(stage_world("obstacle"), offsets)


def test_invalids_do_not_train_and_resume_is_exact():
    method = SceneSearch("afs", 42)
    rows = [{"offsets": [0, 2.4], "evaluation": None} for _ in range(5)]
    point, meta = method.propose(rows)
    assert meta["phase"] == "cold_start" and meta["training_count"] == 0
    assert (point, meta) == SceneSearch("afs", 42).propose(json.loads(json.dumps(rows)))


def test_adaptive_uses_observed_results():
    rows = [
        {"offsets": p, "evaluation": {"utility": y}}
        for p, y in [([-1, -1], -2), ([-1, 1], -1), ([1, -1], 0.5), ([1, 1], 0.4)]
    ]
    point, meta = SceneSearch("afs", 10).propose(rows)
    assert meta["phase"] == "adaptive" and meta["training_count"] == 4
    assert (point, meta) == SceneSearch("afs", 10).propose(rows)
    reversed_rows = [{**r, "evaluation": {"utility": -r["evaluation"]["utility"]}} for r in rows]
    other, _ = SceneSearch("afs", 10).propose(reversed_rows)
    assert point != other


def test_outcome_excludes_execution_errors_and_missing_facts():
    result = {
        "execution": {"status": "SUCCEEDED", "valid": True},
        "task_facts": {
            "navigation_success": True,
            "elapsed_simulation_s": 50,
            "goal_distance_m": 0.2,
        },
    }
    assert outcome(result, 120)["utility"] > 0
    result["task_facts"]["navigation_success"] = False
    assert outcome(result, 120)["failure"] and outcome(result, 120)["utility"] < 0
    result["execution"]["valid"] = False
    assert outcome(result, 120) is None
    result["execution"]["valid"] = True
    del result["task_facts"]["navigation_success"]
    assert outcome(result, 120) is None
