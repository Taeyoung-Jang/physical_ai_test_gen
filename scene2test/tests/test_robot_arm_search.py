"""CPU-only scientific-isolation and durable-request guards."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from robot_arm import search  # noqa: E402
from robot_arm.placement import AXES, checked, save  # noqa: E402


@pytest.fixture
def config(tmp_path):
    c = search.read(
        Path(__file__).resolve().parents[1] / "config/robot_arm_placement_comparison.json"
    )
    c["seeds"] = [7, 11]
    model = tmp_path / "model"
    model.mkdir()
    (model / "weights").write_bytes(b"mock-weights")
    c["robot"]["model_path"] = str(model)
    return c


def prepare(tmp_path, c):
    root = tmp_path / "campaign"
    root.mkdir()
    source = tmp_path / "source.py"
    source.write_text("# frozen")
    save(root / "manifest.json", search.freeze(c, [source]))
    (root / "manifest.sha256").write_text(search.sha(root / "manifest.json"))
    return root


def response(positions, tier="default"):
    return {
        "status": "completed",
        "service_tier": tier,
        "usage": {"input_tokens": 10},
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"positions": positions, "hypothesis": "test"}),
                    }
                ],
            }
        ],
    }


def passing(c, candidate, directory):
    return {"status": "VALID", "task_outcome": "PASS", "scene_seed": candidate["scene_seed"]}


def proposer(body):
    context = json.loads(body["input"][0]["content"])
    return response({a: sum(v) / 2 for a, v in context["bounds_table_local_m"].items()})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, -10, "0"])
def test_position_validation_rejects_bad_values(config, value):
    positions = search.uniform(config, 7, 0)
    positions["bowl_x"] = value
    with pytest.raises(ValueError):
        checked(positions, config["bounds"])


def test_uniform_domain_reproducible_without_resampling(config):
    for seed in config["seeds"]:
        for i in range(config["per_arm"]):
            p = search.uniform(config, seed, i)
            assert p == search.uniform(config, seed, i)
            assert set(p) == set(AXES)
            checked(p, config["bounds"])


def test_equal_budgets_bootstrap_and_own_seed_history(tmp_path, config):
    root = prepare(tmp_path, config)
    bodies = []
    seen = []

    def propose(body):
        bodies.append(body)
        return proposer(body)

    def run(c, candidate, d):
        seen.append((d, candidate))
        return passing(c, candidate, d)

    result = search.run(root, run, propose, max_new=16)
    assert result["equal_valid_budget_complete"]
    assert result["relative_fdr_gain"] is None
    assert all(t["valid"] == 8 for t in result["totals"].values())
    assert result["totals"]["random"]["afs_requests"] == 0
    assert len(bodies) == 4
    for seed in config["seeds"]:
        for i in range(2):
            a = search.read(root / f"seed_{seed}/afs/attempt_{i:05d}/candidate.json")
            b = search.read(root / f"seed_{seed}/random/attempt_{i:05d}/candidate.json")
            assert a == b
    for body in bodies:
        history = json.loads(body["input"][0]["content"])["history"]
        assert len({r["evidence_id"].split("/")[0] for r in history}) == 1
        assert all("/afs/" in r["evidence_id"] for r in history)


def test_saved_response_resume_does_not_call_api(tmp_path, config):
    config["seeds"] = [7]
    root = prepare(tmp_path, config)
    search.run(root, passing, proposer, max_new=4)
    d = root / "seed_7/afs/attempt_00002"
    d.mkdir()
    body = search.proposal_body(config, search.history_for(root, 7, "afs"))
    save(d / "request.json", body)
    save(d / "response.json", proposer(body))

    def forbidden(_):
        pytest.fail("saved response must not be resent")

    search.run(root, passing, forbidden, max_new=1)
    assert search.read(d / "result.json")["task_outcome"] == "PASS"


def test_ambiguous_api_intent_never_resent(tmp_path, config):
    config["seeds"] = [7]
    root = prepare(tmp_path, config)
    search.run(root, passing, proposer, max_new=4)
    d = root / "seed_7/afs/attempt_00002"
    d.mkdir()
    save(d / "request.json", search.proposal_body(config, search.history_for(root, 7, "afs")))
    with pytest.raises(RuntimeError, match="never resend"):
        search.run(root, passing, lambda _: pytest.fail("resend"), max_new=1)


def test_pending_robot_never_rerun(tmp_path, config):
    root = prepare(tmp_path, config)

    def crash(*args):
        raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        search.run(root, crash, proposer)
    with pytest.raises(RuntimeError, match="never rerun"):
        search.run(root, lambda *a: pytest.fail("rerun"), proposer)


def test_exclusion_stops_and_is_not_failure(tmp_path, config):
    root = prepare(tmp_path, config)
    with pytest.raises(RuntimeError, match="no replacement"):
        search.run(root, lambda *a: {"status": "INCONCLUSIVE", "task_outcome": None}, proposer)
    s = search.summary(root)
    assert s["totals"]["afs"]["excluded"] == 1
    assert s["totals"]["afs"]["fail"] == 0
    with pytest.raises(RuntimeError, match="campaign stopped"):
        search.run(root, passing, proposer)


def test_bad_llm_bounds_never_dispatch_robot(tmp_path, config):
    config["seeds"] = [7]
    root = prepare(tmp_path, config)
    search.run(root, passing, proposer, max_new=4)
    positions = search.uniform(config, 7, 2)
    positions["plate_x"] = 1e5
    with pytest.raises(ValueError, match="outside shared bounds"):
        search.run(root, lambda *a: pytest.fail("invalid dispatch"), lambda _: response(positions))
    d = root / "seed_7/afs/attempt_00002"
    assert (d / "response.json").exists()
    assert not (d / "robot_intent.json").exists()


@pytest.mark.parametrize("which", ["source", "model", "manifest"])
def test_freeze_tamper_stops_before_execution(tmp_path, config, which):
    root = prepare(tmp_path, config)
    if which == "source":
        (tmp_path / "source.py").write_text("# changed")
    elif which == "model":
        (Path(config["robot"]["model_path"]) / "weights").write_bytes(b"changed")
    else:
        m = search.read(root / "manifest.json")
        m["config"]["bounds"]["bowl_x"] = [-0.2, -0.05]
        (root / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ValueError, match="changed"):
        search.run(root, lambda *a: pytest.fail("dispatch"), proposer)


def test_no_metric_early_stop(tmp_path, config):
    root = prepare(tmp_path, config)

    def failing(c, candidate, directory):
        return {"status": "VALID", "task_outcome": "FAIL"}

    result = search.run(root, failing, proposer, max_new=16)
    assert result["equal_valid_budget_complete"]
    assert result["relative_fdr_gain"] == 0
    assert not result["statistical_superiority_established"]


def test_unknown_tier_preserves_response_without_robot(tmp_path, config):
    config["seeds"] = [7]
    root = prepare(tmp_path, config)
    search.run(root, passing, proposer, max_new=4)
    with pytest.raises(ValueError, match="service tier"):
        search.run(
            root,
            lambda *a: pytest.fail("dispatch"),
            lambda _: response(search.uniform(config, 7, 2), tier=None),
        )
    assert (root / "seed_7/afs/attempt_00002/response.json").exists()


def test_strict_axis_inventory(config):
    bad = copy.deepcopy(config)
    del bad["bounds"]["bowl_x"]
    with pytest.raises(ValueError):
        search.validate(bad)


def test_saved_candidate_tamper_rejected_before_robot(tmp_path, config):
    root = prepare(tmp_path, config)
    d = root / "seed_7/afs/attempt_00000"
    d.mkdir(parents=True)
    candidate = {
        "positions": search.uniform(config, 7, 0),
        "scene_seed": search.scene_seed(7, 0),
        "hypothesis": "uniform bootstrap",
    }
    candidate["positions"]["bowl_x"] = config["bounds"]["bowl_x"][0]
    save(d / "candidate.json", candidate)
    with pytest.raises(ValueError, match="sampling/response"):
        search.run(root, lambda *a: pytest.fail("tampered dispatch"), proposer)


def test_completed_receipt_collected_without_robot_resend(tmp_path, config):
    root = prepare(tmp_path, config)
    d = root / "seed_7/afs/attempt_00000"
    d.mkdir(parents=True)
    candidate = {"positions": search.uniform(config, 7, 0), "scene_seed": search.scene_seed(7, 0)}
    save(d / "candidate.json", candidate)
    save(d / "robot_intent.json", candidate)
    save(d / "receipt.json", {"status": "VALID", "task_outcome": "PASS"})
    result = search.run(root, lambda *a: pytest.fail("no robot expected"), proposer, max_new=0)
    assert result["totals"]["afs"]["pass"] == 1
    assert (d / "result.json").exists()


def test_adapter_refreshes_observations_and_does_not_repeat_episode(tmp_path, config, monkeypatch):
    import types

    import numpy as np

    from robot_arm import placement

    events = []

    class Raw:
        def reset(self):
            events.append("raw_reset")

        def _update_observables(self, force):
            events.append("refresh")

        def _get_observations(self, force_update):
            return {"fresh": True}

    class Control:
        def __init__(self):
            self.env = Raw()
            self.success = False

        def seed(self, s):
            events.append(("seed", s))

        def check_success(self):
            return self.success

        def get_sim_state(self):
            return np.array([1, 2, 3])

    class Base:
        def __init__(self, **kw):
            self._env = Control()

        def _process_observation(self, obs):
            return obs

        def step(self, action):
            self._env.success = True
            return {"fresh": "final"}, 1, True, False, {"success": True}

    rollout = types.ModuleType("gr00t.eval.rollout_policy")
    libero = types.ModuleType("gr00t.eval.sim.LIBERO.libero_env")
    libero.LiberoEnv = Base
    libero.register_libero_envs = lambda: None
    gym = types.ModuleType("gymnasium")
    gym.spec = lambda name: types.SimpleNamespace(kwargs={})
    for name in ["gr00t", "gr00t.eval", "gr00t.eval.sim", "gr00t.eval.sim.LIBERO"]:
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    sys.modules["gr00t.eval"].rollout_policy = rollout
    monkeypatch.setitem(sys.modules, "gr00t.eval.rollout_policy", rollout)
    monkeypatch.setitem(sys.modules, "gr00t.eval.sim.LIBERO.libero_env", libero)
    monkeypatch.setitem(sys.modules, "gymnasium", gym)
    monkeypatch.setattr(placement, "apply", lambda *a: {"valid": True, "after": {}, "problems": []})
    monkeypatch.setattr(placement, "snapshot", lambda *a: {"bowl": {}})

    def collect(**kw):
        env = rollout.get_libero_env_fn(kw["env_name"])()
        assert env.reset(seed=123)[0] == {"fresh": True}
        env.step({})
        assert env.reset()[0] == {"fresh": "final"}
        assert env.reset()[0] == {"fresh": "final"}
        with pytest.raises(RuntimeError, match="extra episode"):
            env.step({})
        return kw["env_name"], [True], {"episode_lengths": [1]}

    rollout.run_gr00t_sim_policy = collect
    result = placement.run_episode(
        config, {"positions": search.uniform(config, 7, 0), "scene_seed": 700}, tmp_path
    )
    assert result["task_outcome"] == "PASS"
    assert events.count("raw_reset") == 1
    assert ("seed", config["background_seed"]) in events
    assert "refresh" in events
    assert (tmp_path / "initial_state.json").exists()
    assert len((tmp_path / "trace.jsonl").read_text().splitlines()) == 1
