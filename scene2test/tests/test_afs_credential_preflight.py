"""No real credentials, API calls or robot execution."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture
def launcher():
    path = Path(__file__).parents[1] / "tools/run_expanded_afs_checked.py"
    spec = importlib.util.spec_from_file_location("afs_checked_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("key", [None, "", " ", "fake key", "fake\nkey", "키", "fake\x7fkey"])
def test_invalid_key_no_delegate_or_leak(launcher, monkeypatch, capsys, key):
    if key is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", key)
    monkeypatch.setattr(sys, "argv", ["launcher", "--live"])
    with pytest.raises(SystemExit) as exc:
        launcher.main()
    assert exc.value.code == 2
    output = capsys.readouterr().err
    assert "No API request was sent" in output
    if key and key.strip():
        assert key not in output


def test_check_only_no_delegation(launcher, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-secret-never-a-real-key")
    monkeypatch.setattr(sys, "argv", ["launcher", "--check-only"])
    launcher.main()
    output = capsys.readouterr().out
    assert "KEY_PRESENT" in output and "NOT tested" in output
    assert "fake-secret" not in output


@pytest.mark.parametrize("args", [["--offline-demo"], ["--live"], ["--live", "--help"]])
def test_forwards_existing_cli(launcher, monkeypatch, args):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-secret-never-a-real-key")
    calls = []
    monkeypatch.setitem(
        sys.modules, "run_expanded_afs", types.SimpleNamespace(main=lambda: calls.append(1))
    )
    monkeypatch.setattr(sys, "argv", ["launcher", *args])
    launcher.main()
    assert calls == [1]
    assert sys.argv[1:] == args


def test_check_only_rejects_combined_live(launcher, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["launcher", "--check-only", "--live"])
    with pytest.raises(SystemExit) as exc:
        launcher.main()
    assert exc.value.code == 2
