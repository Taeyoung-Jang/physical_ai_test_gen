"""No implicit output token ceilings; offline/mocked checks only."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from test_robot_vlm import PNG, obs

from llm_afs import provider
from robot_vlm.policy import request_body

PROJECT = Path(__file__).parents[1]


@pytest.mark.parametrize("builder", ["robot", "afs"])
@pytest.mark.parametrize("cap", [None, 2048])
def test_request_default_omitted_explicit_cap_preserved(builder, cap):
    build = (
        (lambda **kw: request_body(obs(), PNG, **kw))
        if builder == "robot" else (lambda **kw: provider.request_body({}, {}, **kw))
    )
    assert "max_output_tokens" not in build()
    body = build(max_output_tokens=cap)
    if cap is None:
        assert "max_output_tokens" not in body
    else:
        assert body["max_output_tokens"] == cap
    assert "max_tokens" not in body and "max_completion_tokens" not in body


@pytest.mark.parametrize("builder", ["robot", "afs"])
@pytest.mark.parametrize("cap", [0, -1, 511, 20000])
def test_explicit_invalid_cap_still_rejected(builder, cap):
    with pytest.raises(ValueError):
        if builder == "robot":
            request_body(obs(), PNG, max_output_tokens=cap)
        else:
            provider.request_body({}, {}, max_output_tokens=cap)


@pytest.mark.parametrize(
    "script,config",
    [("run_llm_afs", "llm_afs_terrain.yaml"), ("run_expanded_afs", "llm_afs_expanded.yaml")],
)
@pytest.mark.parametrize("cap", [None, 4096])
def test_afs_cli_has_no_implicit_cap(script, config, cap, tmp_path, monkeypatch):
    # Default mode must only prepare a request, even if a key is present in the shell.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("request preparation must not call the provider")

    monkeypatch.setattr(provider, "call", forbidden)
    spec = importlib.util.spec_from_file_location(script, PROJECT / f"tools/{script}.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    args = [script, "--config", str(PROJECT / "config" / config), "--output-root", str(tmp_path)]
    if cap is not None:
        args.extend(["--max-output-tokens", str(cap)])
    monkeypatch.setattr(sys, "argv", args)
    cli.main()
    run = next(tmp_path.iterdir())
    body = json.loads((run / "request.json").read_text())
    if cap is None:
        assert "max_output_tokens" not in body
    else:
        assert body["max_output_tokens"] == cap
    assert json.loads((run / "status.json").read_text())["api_calls"] == 0
