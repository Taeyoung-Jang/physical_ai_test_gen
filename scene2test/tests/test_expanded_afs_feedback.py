"""Reuse synthetic hashed runner fixture; no real CUDA execution implied."""

from pathlib import Path

import pytest
import test_llm_afs as fixtures
import yaml

from llm_afs import expanded


@pytest.mark.parametrize("tamper", [False, True])
def test_v2_verified_feedback_layout_and_tamper(tmp_path, monkeypatch, tamper):
    cfg = expanded.ExpandedConfig.model_validate(
        yaml.safe_load((Path(__file__).parents[1] / "config/llm_afs_expanded.yaml").read_text())
    )
    monkeypatch.setattr(
        fixtures,
        "compile_scenes",
        lambda config, proposal, root, **kwargs: expanded.compile_scenes(
            config, proposal, root, samples=1, seed=13
        ),
    )
    monkeypatch.setattr(fixtures, "demo_proposal", expanded.demo)
    monkeypatch.setattr(fixtures, "context", lambda config: expanded.context(config, []))
    prior, summary, job = fixtures.feedback.__wrapped__(cfg, tmp_path)
    if tamper:
        # Deliberate fixture mutation verifies the inherited artifact integrity guard.
        (job / "state_trajectory.jsonl").write_text("tampered fixture")
        with pytest.raises(ValueError, match="checksum"):
            expanded.feedback(cfg, prior, summary)
    else:
        rows = expanded.feedback(cfg, prior, summary)
        assert rows[0]["robot_failure"] is True
        assert rows[0]["layout"] == "ramp_then_obstacles"
        assert rows[0]["execution_signature"]
        next_root = tmp_path / "next"
        next_root.mkdir()
        suite = expanded.compile_scenes(
            cfg, expanded.demo(cfg), next_root, samples=4, observations=rows
        )
        assert suite["scenes"][3]["sampler"] == "failure_neighborhood"
        assert suite["scenes"][3]["parent_failure_job"] == job.name
