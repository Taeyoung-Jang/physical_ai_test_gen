import importlib.util
import json
from pathlib import Path

import pytest

mujoco = pytest.importorskip("mujoco")
module_spec = importlib.util.spec_from_file_location(
    "terrain_contact_analysis", Path(__file__).parents[1] / "tools/analyze_terrain_contacts.py"
)
analysis = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(analysis)

XML = """<mujoco><worldbody>
<geom name="world_surface_0" type="plane" size="2 2 .1"/>
<body name="test_ankle_roll" pos="0 0 .09"><freejoint/>
<geom type="sphere" size=".1" mass="1"/></body>
</worldbody></mujoco>"""


def test_unnamed_geom_retains_body_and_id():
    model = mujoco.MjModel.from_xml_string(XML)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    row = analysis.contact_record(model, data.contact[0], 0)
    assert row["geom2"] is None
    assert row["geom2_id"] == 1
    assert row["body2"] == "test_ankle_roll"
    assert row["body2_id"] == 1
    assert row["distance_m"] < 0


def test_analysis_preserves_source_and_refuses_output_reuse(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    (job / "composed_scene.xml").write_text(XML)
    model = mujoco.MjModel.from_xml_string(XML)
    data = mujoco.MjData(model)
    source = job / "state_trajectory.jsonl"
    source.write_text(
        json.dumps({"time_s": 0, "qpos": data.qpos.tolist(), "qvel": data.qvel.tolist()}) + "\n"
    )
    before = source.read_bytes()
    output = tmp_path / "analysis"
    result = analysis.analyze(job, output)
    assert result["sample_count"] == 1
    assert result["contact_counts"]
    assert source.read_bytes() == before
    assert "not dynamics replay" in result["method"]
    with pytest.raises(FileExistsError):
        analysis.analyze(job, output)
