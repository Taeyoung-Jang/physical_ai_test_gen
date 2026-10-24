"""CPU-only fixed-candidate replay, provenance, resume and no-resend checks."""

import sys
from pathlib import Path

import pytest

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "tools"),
    str(Path(__file__).resolve().parents[1] / "src"),
]
import run_robot_arm_reproducibility as repeat  # noqa: E402

from robot_arm import free_pair_search as original  # noqa: E402
from robot_arm import placement, search  # noqa: E402


@pytest.fixture
def prepared(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    design = search.read(repeat.PROJECT / "config/robot_arm_free_pair_comparison.json")
    c = design["experiment"]
    c["seeds"] = [727]
    c["robot"]["model_path"] = str(tmp_path / "empty_model")
    Path(c["robot"]["model_path"]).mkdir()
    m = search.freeze(c, [])
    m.update(mode=original.VERSION, design=design)
    placement.save(source / "manifest.json", m)
    (source / "manifest.sha256").write_text(search.sha(source / "manifest.json"))
    # No proposal needed for this synthetic archive; prepare audits sealed evidence.
    for method in c["methods"]:
        for index in range(4):
            d = source / f"seed_727/{method}/attempt_{index:05d}"
            d.mkdir(parents=True)
            v = original.candidate(design, original.uniform(design, 727, index), 727, index, "mock")
            placement.save(d / "candidate.json", v)
            placement.save(d / "robot_intent.json", v)
            r = {
                "status": "VALID",
                "task_outcome": "FAIL" if index % 2 else "PASS",
                "scene_seed": v["scene_seed"],
            }
            if method == "afs" and index == 0:
                r = {
                    "status": "INCONCLUSIVE",
                    "task_outcome": None,
                    "reason": "preserved_pre_rollout_user_cancel",
                }
            placement.save(d / "receipt.json", r)
            placement.save(d / "measurement.json", {"status": "COMPLETE", "contact": False})
            original.seal(d)
    root = tmp_path / "repeats"
    repeat.prepare(source, root)
    return source, root


def fake(c, v, d):
    placement.save(
        d / "receipt.json",
        {"status": "VALID", "task_outcome": "FAIL", "scene_seed": v["scene_seed"]},
    )
    placement.save(d / "measurement.json", {"status": "COMPLETE", "contact": False})
    original.seal(d)


def test_complete_same_seed_all_valid_environments_and_resume(prepared):
    source, root = prepared
    before = {p: search.sha(p) for p in source.rglob("*") if p.is_file()}
    seen = []

    def runner(c, v, d):
        rel = Path(*d.relative_to(root).parts[1:])
        assert v == search.read(source / rel / "candidate.json")
        assert not (source / rel / "receipt.json").read_text().find('"INCONCLUSIVE"') >= 0
        seen.append(d)
        fake(c, v, d)

    partial = repeat.run(root, runner, 1)
    assert not partial["complete"] and len(seen) == 1
    result = repeat.run(root, runner, 46)
    assert len(seen) == 14 and result["complete"]
    assert result["totals"]["afs"]["environments"] == 3
    assert result["totals"]["random"]["environments"] == 4
    assert result["totals"]["afs"]["three_fail"] == 2
    assert result["totals"]["random"]["mixed"] == 2
    assert len(result["excluded_source_slots"]) == 1
    assert not list(root.rglob("request.json"))
    repeat.run(root, lambda *args: pytest.fail("completed repeat rerun"), 46)
    assert before == {p: search.sha(p) for p in source.rglob("*") if p.is_file()}
    with pytest.raises(FileExistsError):
        repeat.prepare(source, root)


def test_pending_intent_stops_without_replacement(prepared):
    _, root = prepared

    def interrupted(*args):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        repeat.run(root, interrupted, 46)
    assert repeat.report(root)["totals"]["afs"]["pending"] == 1
    with pytest.raises(RuntimeError, match="pending repeat intent"):
        repeat.run(root, lambda *args: pytest.fail("resent"), 46)


def test_excluded_repeat_stops_and_never_counts_fail(prepared):
    _, root = prepared

    def excluded(c, v, d):
        placement.save(d / "receipt.json", {"status": "INCONCLUSIVE", "task_outcome": None})
        placement.save(d / "measurement.json", {"status": "UNKNOWN"})
        original.seal(d)

    with pytest.raises(RuntimeError, match="excluded repeat"):
        repeat.run(root, excluded, 46)
    r = repeat.report(root)
    assert r["totals"]["afs"]["new_excluded"] == 1
    assert r["totals"]["afs"]["complete_three"] == 0
    with pytest.raises(RuntimeError, match="excluded repeat"):
        repeat.run(root, lambda *args: pytest.fail("replacement"), 46)


def test_changed_source_and_repeat_seed_rejected(prepared):
    source, root = prepared
    target = next(source.glob("seed_727/random/attempt_00000/candidate.json"))
    target.write_text(target.read_text() + "\n")
    with pytest.raises(ValueError, match="inherited artifact changed"):
        repeat.run(root, fake, 46)


def test_wrong_seed_sealed_receipt_rejected(prepared):
    _, root = prepared

    def bad(c, v, d):
        fake(c, v, d)
        r = search.read(d / "receipt.json")
        r["scene_seed"] += 1
        (d / "receipt.json").write_text(__import__("json").dumps(r))
        (d / "evidence_manifest.json").unlink()
        original.seal(d)

    with pytest.raises(ValueError, match="seed mismatch"):
        repeat.run(root, bad, 46)


def test_summary_updates_without_rewriting_evidence(prepared):
    _, root = prepared
    repeat.save_summary(root, repeat.report(root))
    result = repeat.run(root, fake, 1)
    repeat.save_summary(root, result)
    assert search.read(root / "summary.json") == result
    assert not list(root.glob("summary_*.tmp"))
