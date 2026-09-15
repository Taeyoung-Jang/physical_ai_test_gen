"""CLI opt-in safety and supported execution-contract checks; no paid calls."""

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest
import yaml

from llm_afs import provider
from llm_afs.contracts import Config

PROJECT = Path(__file__).parents[1]


def load_cli():
    spec = importlib.util.spec_from_file_location("llm_afs_cli", PROJECT / "tools/run_llm_afs.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli


def test_default_cli_does_not_call_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")

    def forbidden(*args, **kwargs):
        pytest.fail("default mode must not invoke provider")

    monkeypatch.setattr(provider, "call", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_llm_afs",
            "--config",
            str(PROJECT / "config/llm_afs_terrain.yaml"),
            "--output-root",
            str(tmp_path),
        ],
    )
    load_cli().main()
    run = next(tmp_path.iterdir())
    assert json.loads((run / "status.json").read_text())["api_calls"] == 0
    assert not (run / "suite.json").exists()
    assert all("test-placeholder" not in p.read_text() for p in run.iterdir())


def test_missing_key_cli_preserves_request_without_api(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_llm_afs",
            "--live",
            "--config",
            str(PROJECT / "config/llm_afs_terrain.yaml"),
            "--output-root",
            str(tmp_path),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        load_cli().main()
    assert exc.value.code == 2
    run = next(tmp_path.iterdir())
    assert (run / "request.json").exists()
    assert json.loads((run / "status.json").read_text())["status"] == "ERROR"
    assert not (run / "api_response.json").exists()


@pytest.mark.parametrize("kind", ["vlm", "pose", "timestep", "endpoints", "bool", "inverted"])
def test_unsupported_config_rejected(kind):
    cfg = yaml.safe_load((PROJECT / "config/llm_afs_terrain.yaml").read_text())
    if kind == "vlm":
        cfg["policy_spec"]["robot_vlm_enabled"] = True
    elif kind == "pose":
        cfg["observation_spec"]["localization"] = "visual_slam"
    elif kind == "timestep":
        cfg["task_spec"]["physics_timestep_s"] = 0.01
    elif kind == "endpoints":
        cfg["domains"] = [{"path": "segments.0.length_m", "low": 1.0, "high": 3.0}]
    elif kind == "bool":
        cfg["domains"][0]["low"] = True
    else:
        cfg["domains"][0]["low"] = 13.0
    with pytest.raises(ValueError):
        Config.model_validate(cfg)


def test_api_timeout_is_bounded_no_retry(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("test-placeholder")

    with pytest.raises(RuntimeError, match="no automatic retry") as exc:
        provider.call({}, transport=httpx.MockTransport(handler))
    assert len(calls) == 1
    assert "test-placeholder" not in str(exc.value)
