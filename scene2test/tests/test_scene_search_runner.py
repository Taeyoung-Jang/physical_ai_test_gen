"""Pilot budget and interruption tests without running physics or writing runtime."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

from procedural_world.navigation_stages import stage_world
from procedural_world.search import InvalidScene


def runner_module():
    path = Path(__file__).resolve().parents[1] / "tools/run_scene_search.py"
    spec = importlib.util.spec_from_file_location("scene_search_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_valid_budget_and_resume_after_lost_acceptance(tmp_path, monkeypatch):
    module = runner_module()
    base = stage_world("obstacle")
    jobs = {}
    lost_response = [True]
    rejected = [False]

    class Response:
        content = b"verified artifact"

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            if url.endswith("/registry/snapshot"):
                return Response(
                    {
                        "robots": [{"id": "unitree_g1_locomotion", "revision": "robot"}],
                        "controllers": [{"id": "groot_locomotion", "revision": "controller"}],
                        "policies": [{"id": "groot_walk_policy", "revision": "policy"}],
                    }
                )
            if url.endswith("/result"):
                job = url.split("/")[-2]
                # The first completed job is an execution error, not a task failure.
                valid = job != "job_0"
                return Response(
                    {
                        "execution": {
                            "status": "SUCCEEDED" if valid else "FAILED",
                            "valid": valid,
                            "termination_reason": "TEST",
                        },
                        "task_facts": {
                            "navigation_success": True,
                            "elapsed_simulation_s": 50,
                            "goal_distance_m": 0.2,
                        },
                        "artifacts": [
                            {
                                "artifact_id": f"{job}:test",
                                "size_bytes": len(Response.content),
                                "sha256": hashlib.sha256(Response.content).hexdigest(),
                            }
                        ],
                        "reproduction": {
                            "runtime": {"execution_provider": "CUDAExecutionProvider"},
                            "scene_revision": base.revision,
                        },
                    }
                )
            return Response({"status": "SUCCEEDED"})

        def post(self, url, json, headers):
            key = headers["Idempotency-Key"]
            job = jobs.setdefault(key, f"job_{len(jobs)}")
            if lost_response[0]:
                lost_response[0] = False
                raise httpx.ReadError("acceptance response lost after server persisted job")
            return Response({"job_id": job})

    def mutate(*args):
        if not rejected[0]:
            rejected[0] = True
            raise InvalidScene("GEOMETRY_OVERLAP")
        return base

    def export(spec, root):
        path = root / spec.scene_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(module.httpx, "Client", Client)
    monkeypatch.setattr(module, "move_obstacle", mutate)
    monkeypatch.setattr(module, "export_bundle", export)
    monkeypatch.setattr(
        module,
        "register_world",
        lambda *args: {"id": base.scene_id, "revision": "sha256:" + base.revision},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["runner", "--output-root", str(tmp_path), "--valid-budget", "5", "--max-attempts", "9"],
    )
    with pytest.raises(httpx.ReadError):
        module.main()
    run = next(tmp_path.iterdir())
    rows = json.loads((run / "journal.json").read_text())
    assert [r["status"] for r in rows] == ["INVALID_SCENE", "PENDING"]
    assert len(jobs) == 1
    monkeypatch.setattr(sys, "argv", ["runner", "--resume", str(run)])
    module.main()
    summary = json.loads((run / "summary.json").read_text())
    assert summary["complete"]
    assert len(jobs) == 16  # 15 valid + 1 execution error, no duplicate after lost response
    assert all(s["valid_rollouts"] == 5 and s["failures"] == 0 for s in summary["methods"].values())
    assert summary["methods"]["random"]["statuses"] == {
        "INVALID_SCENE": 1,
        "EXECUTION_ERROR": 1,
        "EVALUATED": 5,
    }
    assert summary["methods"]["afs"]["adaptive_rollouts"] == 1


def test_incomplete_report_does_not_claim_budget_complete(tmp_path):
    module = runner_module()
    protocol = {"methods": ["random", "sobol", "afs"], "valid_budget": 8}
    rows = [{"method": "random", "status": "INVALID_SCENE", "evaluation": None}]
    report = module.report(tmp_path, protocol, rows)
    assert not report["complete"]
    assert report["methods"]["random"]["valid_rollouts"] == 0
    assert report["methods"]["random"]["failure_rate"] is None
