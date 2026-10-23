"""Standard continuation orchestration with fake suites, no API/GPU/robot."""

import importlib.util
from pathlib import Path

import pytest


def driver():
    path = Path(__file__).resolve().parents[2] / "tools/run_sol_standard_regression.py"
    spec = importlib.util.spec_from_file_location("standard_driver", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("excluded_group", [None, "safety"])
def test_budget_resume_and_exclusion_stop(tmp_path, monkeypatch, excluded_group):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    m = driver()
    prior = {"source": "preserved", "spent_attempts": 1, "usage_status": "unknown_not_zero"}
    monkeypatch.setattr(m, "prior_snapshot", lambda: prior)
    planned = [(name, {"max_attempts": repeats}) for name, repeats, _ in m.GROUPS]
    monkeypatch.setattr(m, "plans", lambda: planned)
    states, calls = {}, []

    class Suite:
        @classmethod
        def create(cls, root, plan):
            states[root] = {"lock": {"plan": plan}, "status": "READY", "attempts": 0}

        def __init__(self, root):
            self.root, self.state = root, states[root]

        def run(self, **kwargs):
            assert kwargs == {"live": True, "max_new_attempts": 2}
            if self.state["status"] == "READY":
                calls.append(self.root.name)
                self.state["attempts"] = (
                    1
                    if self.root.name == excluded_group
                    else self.state["lock"]["plan"]["max_attempts"]
                )
                self.state["status"] = (
                    "NEEDS_ATTENTION" if self.root.name == excluded_group else "COMPLETE"
                )
            return self.summary()

        def summary(self):
            return {
                "status": self.state["status"],
                "cases": [{"attempted": self.state["attempts"]}],
            }

        def report(self):
            return self.root / "report.html"

    monkeypatch.setattr(m, "BehaviorRegression", Suite)
    root = tmp_path / "standard"
    assert m.main(["init", "--root", str(root)]) == 0
    assert m.main(["run", "--root", str(root), "--live"]) == 2  # no key
    assert not calls
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-only")
    assert m.main(["run", "--root", str(root), "--live"]) == (2 if excluded_group else 0)
    value = m.summary(root)
    assert value["combined_attempts"] <= 6
    assert value["new_robot_call_upper_bound"] == 50
    assert calls == (["pass", "safety"] if excluded_group else ["pass", "safety", "occupied"])
    count = len(calls)
    m.main(["run", "--root", str(root), "--live"])
    assert len(calls) == count  # no reset or automatic exclusion continuation
    with pytest.raises(ValueError, match="prior Flex evidence changed"):
        monkeypatch.setattr(m, "prior_snapshot", lambda: {**prior, "spent_attempts": 2})
        m.summary(root)
