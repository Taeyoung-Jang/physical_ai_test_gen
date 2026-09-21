import json
import os
from pathlib import Path

import jsonschema
import pytest

from robot_vlm.push_execution import permitted
from robot_vlm.push_policy import PushAction, PushEnvelope
from robot_vlm.wire_contract import GoalEnvelope, schema


def push(version=0, target=None):
    return dict(
        state_version=version,
        plan_summary="MOCK integration wiring",
        action="push_object",
        object_id="clear_box_geom",
        target_xy_m=target or [4.08, 0.0],
        skill_request=None,
        vx_mps=0.0,
        vy_mps=0.0,
        yaw_rate_rps=0.0,
        duration_s=18.0,
    )


def test_push_wire_and_disabled_contract():
    value = {"command": push()}
    jsonschema.validate(value, schema(PushEnvelope))
    assert PushEnvelope.model_validate(value).command.action == "push_object"
    with pytest.raises(ValueError):
        GoalEnvelope.model_validate(value)


@pytest.mark.parametrize(
    "change",
    [{"duration_s": 10.0}, {"object_id": "wall_south"}, {"target_xy_m": [4.0]}, {"vx_mps": 0.1}],
)
def test_invalid_push_rejected_by_wire_and_parser(change):
    value = {"command": push() | change}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(value, schema(PushEnvelope))
    with pytest.raises(ValueError):
        PushEnvelope.model_validate(value)


def test_contact_exemption_is_scoped():
    from types import SimpleNamespace

    s = SimpleNamespace(control=SimpleNamespace(phase="push"))
    assert permitted(s, 10, 20, {10}, 20)
    assert not permitted(None, 10, 20, {10}, 20)
    assert not permitted(s, 11, 20, {10}, 20)
    assert not permitted(s, 10, 21, {10}, 20)
    s.control.phase = "settle"
    assert not permitted(s, 10, 20, {10}, 20)


@pytest.mark.skipif(os.getenv("RUN_ROBOT_PUSH_GPU") != "1", reason="explicit GPU integration")
@pytest.mark.parametrize("near_box", [True, False])
def test_gpu_push_handoff_and_updated_map(monkeypatch, near_box):
    import hashlib
    from datetime import datetime, timezone

    from clear_path import audit
    from robot_vlm.goal_policy import GoalAction
    from robot_vlm.goal_runner import run
    from robot_vlm.push_policy import PushMock

    if near_box:
        original = audit.initial_data

        def init(model, source):
            data = original(model, source)
            data.qpos[0] = 3.2  # Test setup only, before any physics step.
            return data

        monkeypatch.setattr(audit, "initial_data", init)

    class Script(PushMock):
        pushed = False
        after = 0

        def decide(self, obs, png):
            v = obs.state_version
            if not self.pushed and obs.base_xyz_m[0] >= 3.13:
                self.pushed = True
                box = next(g for g in obs.geometry if g.object_id == "clear_box_geom")
                return PushAction(**push(v, [box.center_m[0] + 0.08, box.center_m[1]])), {
                    "origin": "mock"
                }
            action = dict(
                state_version=v,
                plan_summary="MOCK integration, not autonomous",
                skill_request=None,
                vx_mps=0.0,
                vy_mps=0.0,
                yaw_rate_rps=0.0,
            )
            if not self.pushed:
                if obs.base_xyz_m[0] < 2.95:
                    action.update(action="navigate_to", target_xy_m=[3.15, 0.0], duration_s=10.0)
                else:
                    action.update(action="move", target_xy_m=None, vx_mps=0.1, duration_s=1.0)
            else:
                self.after += 1
                if self.after == 1:
                    action.update(action="move", target_xy_m=None, vx_mps=-0.1, duration_s=2.0)
                elif self.after == 2:
                    action.update(action="plan_path", target_xy_m=[7.0, 0.0], duration_s=0.2)
                elif self.after == 3:
                    action.update(action="navigate_to", target_xy_m=[2.5, 0.0], duration_s=3.0)
                else:
                    action.update(action="stop", target_xy_m=None, duration_s=0.2)
            return GoalAction(**action), {"origin": "mock"}

    root = Path("/workspace/g1_failure/runtime/robot_push_integration") / datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%S_%fZ")
    root.mkdir(parents=True)
    print("PUSH_INTEGRATION=", root, "near_box=", near_box, flush=True)
    result = run(
        root,
        Path("/workspace/g1_failure/src/GR00T-WholeBodyControl"),
        Script(),
        enable_push=True,
        max_calls=14,
        max_seconds=110,
    )
    assert result["valid_execution"] and result["reason"] == "POLICY_STOP"
    skills = list(root.glob("skill_*.json"))
    assert len(skills) == 1
    skill = json.loads(skills[0].read_text())
    assert skill["released"] and skill["handoff_complete"]
    assert skill["contact_seconds"] > 0
    assert skill["displacement_push_frame_m"][0] > 0.02
    # Verify changed physical geometry is present in the next observation used by the planner.
    version = int(skills[0].stem.split("_")[1])
    obs = json.loads((root / f"observation_{version + 1:03}.json").read_text())
    box = next(g for g in obs["geometry"] if g["object_id"] == "clear_box_geom")
    assert abs(box["center_m"][0] - skill["actual_box_xyz_m"][0]) < 0.01
    for item in json.loads((root / "manifest.json").read_text())["artifacts"]:
        assert hashlib.sha256((root / item["path"]).read_bytes()).hexdigest() == item["sha256"]
