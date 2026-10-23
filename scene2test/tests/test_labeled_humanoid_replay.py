"""Replay integrity guards and camera projection; no rollout or rendering needed."""

import hashlib
import json
import runpy
from types import SimpleNamespace

import pytest


@pytest.fixture
def module():
    return runpy.run_path("tools/render_labeled_humanoid.py")


def archive(root):
    entries = []
    for name in ("scene.xml", "states.jsonl", "human_motion.jsonl", "result.json"):
        (root / name).write_text("synthetic")
        entries.append({"path": name, "sha256": hashlib.sha256(b"synthetic").hexdigest()})
    (root / "manifest.json").write_text(json.dumps({"artifacts": entries}))


def test_verified_archive_refuses_tampering(module, tmp_path):
    archive(tmp_path)
    assert len(module["verified_archive"](tmp_path)) == 4
    (tmp_path / "states.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        module["verified_archive"](tmp_path)


@pytest.mark.parametrize("name", ["../outside", "scene.xml"])
def test_unsafe_or_duplicate_manifest_refused(module, tmp_path, name):
    archive(tmp_path)
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["artifacts"].append({"path": name, "sha256": "unused"})
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="unsafe or duplicate"):
        module["verified_archive"](tmp_path)


def test_projection_places_labels_at_actual_camera_points(module):
    camera = SimpleNamespace(
        pos=[0, 0, 0],
        forward=[0, 0, -1],
        up=[0, 1, 0],
        frustum_near=1,
        frustum_top=1,
        frustum_bottom=-1,
        frustum_width=0,
        frustum_center=0,
    )
    project = module["project"]
    assert project([0, 0, -2], camera, 960, 540) == pytest.approx([480, 270])
    assert project([1, 0, -2], camera, 960, 540)[0] > 480
    assert project([0, 1, -2], camera, 960, 540)[1] < 270
    assert project([0, 0, 2], camera, 960, 540) is None
