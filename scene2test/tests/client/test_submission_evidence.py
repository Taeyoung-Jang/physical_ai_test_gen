"""Offline temporary-file export checks; never touch real archives or call models."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def driver():
    path = Path(__file__).resolve().parents[2] / "tools/export_submission_evidence.py"
    spec = importlib.util.spec_from_file_location("submission_export", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_snapshot_copies_verifies_and_never_overwrites(tmp_path, monkeypatch):
    m = driver()
    source = tmp_path / "source"
    write(
        source / "attempts.json",
        [
            {
                "id": "a",
                "episode": {
                    "status": "VALID",
                    "task_outcome": "FAIL",
                    "source": {"path": "original"},
                    "attribution": {"primary_family": "goal_occupied"},
                },
            }
        ],
    )
    (source / "report.html").write_text("source report")
    (source / "rollout.mp4").write_bytes(b"synthetic-media")
    originals = {p.name: m.sha(p) for p in source.iterdir()}
    write(
        source / "manifest.json",
        {"artifacts": [{"path": name, "sha256": checksum} for name, checksum in originals.items()]},
    )
    monkeypatch.setattr(m, "probe", lambda _: {"readable_metadata": False})
    audit = {
        "scope": "synthetic",
        "archives": [],
        "archive_count": 0,
        "with_mp4": 0,
        "without_mp4": 0,
        "with_gif": 0,
    }
    target = tmp_path / "output"
    result = m.export(target, [("report_test", source)], audit)
    assert result["files"] == 4 and result["metadata_unreadable"] == 1
    assert all(m.sha(source / name) == checksum for name, checksum in originals.items())
    for entry in m.read(target / "manifest.json")["artifacts"]:
        assert m.sha(target / entry["path"]) == entry["sha256"]
    assert m.read(target / "report_records.json")[0]["primary_family"] == "goal_occupied"
    monkeypatch.setattr(m, "inventory", lambda _: audit)
    m.refresh_inventory(target, tmp_path)
    for entry in m.read(target / "manifest.json")["artifacts"]:
        assert m.sha(target / entry["path"]) == entry["sha256"]
    with pytest.raises(ValueError, match="new and separate"):
        m.export(target, [("report_test", source)], audit)
    with pytest.raises(ValueError, match="new and separate"):
        m.export(source / "nested", [("report_test", source)], audit)


@pytest.mark.parametrize("kind", ["escape", "changed", "symlink"])
def test_bad_source_is_rejected(tmp_path, kind):
    m = driver()
    source = tmp_path / "source"
    source.mkdir()
    data = source / "data.json"
    data.write_text("original")
    if kind == "symlink":
        (source / "link").symlink_to(data)
    else:
        write(
            source / "manifest.json",
            {
                "artifacts": [
                    {
                        "path": "../outside" if kind == "escape" else "data.json",
                        "sha256": "0" * 64,
                    }
                ]
            },
        )
    with pytest.raises(ValueError):
        m.copy_group(source, tmp_path / "out/evidence", tmp_path / "out")


def test_inventory_discloses_missing_media_and_scope(tmp_path, monkeypatch):
    m = driver()
    write(tmp_path / "valid/protocol.json", {"schema_version": "robot-goal-agent-v5"})
    write(tmp_path / "valid/result.json", {"task_outcome": "FAIL"})
    (tmp_path / "valid/rollout.mp4").write_bytes(b"not-decoded")
    write(tmp_path / "partial/protocol.json", {"schema_version": "robot-goal-agent-v5"})
    write(tmp_path / "preview/protocol.json", {"schema_version": "preview-v1"})
    write(
        tmp_path / "report_submission/copy/protocol.json", {"schema_version": "robot-goal-agent-v5"}
    )
    write(
        tmp_path / "trial/reports/snapshot/behavior/evidence/copy/protocol.json",
        {"schema_version": "robot-goal-agent-v5"},
    )
    write(
        tmp_path / "audit/memory/evidence/copy/protocol.json",
        {"schema_version": "robot-goal-agent-v5"},
    )
    paths = [str(p) for p in tmp_path.rglob("*") if p.is_file() and p.name != "result.json"]
    monkeypatch.setattr(
        m.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="\n".join(paths))
    )
    audit = m.inventory(tmp_path)
    assert audit["archive_count"] == 2
    assert audit["with_mp4"] == 1 and audit["without_mp4"] == 1
    assert "not full decode" in audit["media_check"]
