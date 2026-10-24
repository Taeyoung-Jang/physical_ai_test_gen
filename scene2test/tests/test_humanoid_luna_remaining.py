"""Luna-only remaining budget and Bash orchestration; no API or robot execution."""

import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from failure_client.experiments.paired_discovery import PairedDesign

PROJECT = Path(__file__).resolve().parents[1]


def test_luna_remaining_configs_keep_domain_and_charge_new_baselines():
    random_design = runpy.run_path(str(PROJECT / "tools/run_humanoid_random_assessment.py"))[
        "RandomDesign"
    ]
    for method, count, cls, previous in (
        ("afs", 7, PairedDesign, "humanoid_vulnerability_10_pro_timeout600.json"),
        ("random", 3, random_design, "humanoid_random_vulnerability_10_pro_timeout600.json"),
    ):
        data = json.loads((PROJECT / f"config/humanoid_luna_remaining_{method}.json").read_text())
        old = json.loads((PROJECT / "config" / previous).read_text())
        design = cls.model_validate(data)
        assert design.methods == [method]
        assert design.valid_per_arm == design.attempts_per_arm == count
        assert design.cold_start_per_arm == 1
        assert design.seeds == [75002]
        assert design.search.afs_model == "openai/gpt-6-luna"
        assert design.search.afs_api_provider == "openrouter"
        assert design.search.afs_timeout_s == 600
        assert design.scene_domain["axes"] == old["scene_domain"]["axes"]
        assert design.matched_local == old["matched_local"]
        assert design.afs_requests_per_seed == (9 if method == "afs" else 0)


@pytest.mark.parametrize(
    ("script_name", "max_calls"),
    [
        ("run_humanoid_luna_remaining.sh", 10),
        ("run_humanoid_luna_20calls.sh", 20),
        ("run_humanoid_luna_128k.sh", 20),
    ],
)
def test_bash_model_budget_resume_and_independent_random(tmp_path, script_name, max_calls):
    (tmp_path / "tools").mkdir()
    (tmp_path / "bin").mkdir()
    script = tmp_path / "tools" / script_name
    shutil.copyfile(PROJECT / "tools" / script.name, script)
    fake = tmp_path / "bin/uv"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "a = sys.argv[1:]\n"
        "with open(os.environ['MOCK_CALL_LOG'], 'a') as f: f.write(json.dumps(a)+'\\n')\n"
        "if 'tools/run_robot_goal_agent.py' in a:\n"
        " assert a[a.index('--model')+1] == 'openai/gpt-6-luna'\n"
        " assert a[a.index('--response-timeout')+1] == '600'\n"
        f" assert a[a.index('--max-calls')+1] == '{max_calls}'\n"
        " Path(a[a.index('--run-dir')+1]).mkdir(parents=True)\n"
        "elif 'init' in a:\n"
        " Path(a[a.index('--output-dir')+1]).mkdir(parents=True)\n"
        "elif 'tools/run_humanoid_assessment.py' in a:\n"
        " raise SystemExit(2)\n"
    )
    fake.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    env = dict(
        os.environ,
        PATH=str(tmp_path / "bin") + os.pathsep + os.environ["PATH"],
        MOCK_CALL_LOG=str(log),
    )
    for _ in range(2):
        result = subprocess.run(["bash", str(script), "both"], env=env, capture_output=True)
        assert result.returncode == 2, result.stderr.decode()
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert sum("tools/run_robot_goal_agent.py" in a for a in calls) == 1
    assert sum("init" in a for a in calls) == 2
    random_script = "tools/run_humanoid_random_assessment.py"
    assert sum(random_script in a and a[a.index(random_script) + 1] == "run" for a in calls) == 2
    assert any("config/humanoid_luna_remaining_afs.json" in a for a in calls)
    assert any("config/humanoid_luna_remaining_random.json" in a for a in calls)


def test_twenty_call_budget_propagates_to_both_arms_and_total_cap(tmp_path):
    from failure_client.experiments.local_goal_adapter import command
    from failure_client.experiments.research_protocol import CampaignConfig, RobotSettings

    cfg = CampaignConfig(
        robot=RobotSettings(
            model="openai/gpt-6-luna",
            api_provider="openrouter",
            max_calls=20,
            response_timeout=600.0,
        )
    )
    for method in ("afs", "random"):
        args = command(cfg, tmp_path / "scene.json", tmp_path / method)
        assert args[args.index("--max-calls") + 1] == "20"
        assert args[args.index("--response-timeout") + 1] == "600.0"
    audit = json.loads(
        (PROJECT / "config/humanoid_luna_remaining_20calls_transition.json").read_text()
    )
    episodes = sum(audit["remaining_environment_probes"].values()) + sum(
        audit["additional_baselines"].values()
    )
    assert audit["robot_api_calls_per_episode"] == 20
    assert audit["robot_api_call_cap"] == episodes * 20 == 220
    script = (PROJECT / "tools/run_humanoid_luna_20calls.sh").read_text()
    assert 'protocol["max_calls"] != 20' in script
    assert "development/humanoid_luna_20calls_20261023_v4" in script
