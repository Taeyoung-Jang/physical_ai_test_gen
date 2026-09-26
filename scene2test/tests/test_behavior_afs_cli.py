import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_behavior_afs import archive, observation, proposal

from clear_path.fixture import world_xml
from llm_afs import behavior as b
from robot_vlm.scene_config import validate_scene


def test_prepare_never_calls_api_even_with_key(tmp_path):
    run = archive(tmp_path / "evidence")
    tool = Path(__file__).parents[1] / "tools/run_behavior_afs.py"
    result = subprocess.run(
        [sys.executable, str(tool), "--run", str(run), "--output-root", str(tmp_path / "out")],
        env={**os.environ, "OPENAI_API_KEY": "invalid-test-key-not-used"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    output = next((tmp_path / "out").iterdir())
    assert b.read(output / "status.json") == {"origin": "prepare_only", "robot_launched": False}
    assert not (output / "response.json").exists()
    assert not (output / "suite.json").exists()
    assert "invalid-test-key" not in (output / "request.json").read_text()


def test_scene_parameters_reach_mujoco_model(tmp_path):
    mj = pytest.importorskip("mujoco")
    ctx = b.context(observation())
    suite = b.compile_suite(ctx, proposal(ctx), tmp_path)
    for row in suite["candidates"]:
        config = validate_scene(b.read(row["config"]))
        model = mj.MjModel.from_xml_string(world_xml(config))
        box = model.geom("clear_box_geom").id
        floor = model.geom("clear_floor").id
        assert model.body_mass[model.geom_bodyid[box]] == pytest.approx(config.box_mass_kg)
        assert model.geom_friction[box, 0] == pytest.approx(config.box_friction)
        assert model.geom_friction[floor, 0] == pytest.approx(config.floor_friction)
