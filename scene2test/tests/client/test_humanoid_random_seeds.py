import json
import runpy
from pathlib import Path

import pytest

from llm_afs.behavior import digest


def functions():
    return runpy.run_path(str(Path(__file__).parents[2] / "tools/humanoid_repetition_seeds.py"))


def test_assigns_distinct_random_seeds_once_and_preserves_on_resume(tmp_path):
    f = functions()
    numbers = iter([3, 3, 8, 12])
    seeds = f["assign"](tmp_path, randbelow=lambda _: next(numbers))
    assert seeds == [4, 9, 13]
    original = (tmp_path / "seed_assignment.json").read_bytes()

    def forbidden(_):
        raise AssertionError("resume must never draw new seeds")

    assert f["assign"](tmp_path, randbelow=forbidden) == seeds
    assert f["read"](tmp_path) == seeds
    assert (tmp_path / "seed_assignment.json").read_bytes() == original


def test_frozen_old_bundle_keeps_its_seeds_without_reallocation(tmp_path):
    f = functions()
    value = {"repetitions": [{"seed": s, "directory": f"seed_{s}"} for s in [75101, 75102, 75103]]}
    (tmp_path / "repetitions.json").write_text(
        json.dumps({"value": value, "sha256": digest(value)})
    )
    assert f["assign"](tmp_path) == [75101, 75102, 75103]
    assert not (tmp_path / "seed_assignment.json").exists()


def test_changed_assignment_or_partial_campaign_never_rerolls(tmp_path):
    f = functions()
    (tmp_path / "seed_12").mkdir()
    with pytest.raises(ValueError, match="never reroll"):
        f["assign"](tmp_path)
    (tmp_path / "seed_12").rmdir()
    f["assign"](tmp_path)
    saved = json.loads((tmp_path / "seed_assignment.json").read_text())
    saved["value"]["seeds"][0] += 1
    (tmp_path / "seed_assignment.json").write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="digest"):
        f["assign"](tmp_path)
