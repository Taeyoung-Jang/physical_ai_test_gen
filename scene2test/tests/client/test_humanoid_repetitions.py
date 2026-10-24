import json
import math
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

from failure_client.experiments.paired_discovery import PairedDesign

PROJECT = Path(__file__).parents[2]


def test_predeclared_three_equal_budget_designs():
    designs = [
        PairedDesign.model_validate(
            json.loads((PROJECT / f"config/humanoid_replication_{seed}.json").read_text())
        )
        for seed in (75101, 75102, 75103)
    ]
    assert [d.seeds for d in designs] == [[75101], [75102], [75103]]
    for d in designs:
        assert d.methods == ["afs", "random"]
        assert d.valid_per_arm == d.attempts_per_arm == 7
        assert d.cold_start_per_arm == 1 and d.afs_requests_per_seed == 9
        assert d.search.afs_model == "openai/gpt-6-luna"
        assert d.search.afs_api_provider == "openrouter" and d.search.afs_timeout_s == 600
        assert d.matched_local == designs[0].matched_local
        assert d.scene_domain == designs[0].scene_domain


def test_summary_requires_three_complete_pairs_and_reports_seed_variation():
    f = runpy.run_path(str(PROJECT / "tools/report_humanoid_repetitions.py"))
    rows = [
        {"seed": i, "complete": True, "arms": {"afs": {"fail": a}, "random": {"fail": r}}}
        for i, a, r in [(1, 2, 0), (2, 1, 1), (3, 3, 0)]
    ]
    result = f["describe"](rows)
    assert result["all_complete"] and not result["statistical_superiority_established"]
    assert result["by_method"]["afs"]["valid"] == 21
    assert math.isclose(result["by_method"]["afs"]["mean_failure_rate"], 2 / 7)
    assert math.isclose(result["by_method"]["afs"]["sample_std_failure_rate"], 1 / 7)
    rows[-1]["complete"] = False
    partial = f["describe"](rows)
    assert partial["complete_pairs"] == 2 and "by_method" not in partial


def test_bash_three_rounds_no_auto_retry_and_dry_run_is_readonly(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "bin").mkdir()
    script = tmp_path / "tools/run_humanoid_repetitions.sh"
    shutil.copyfile(PROJECT / "tools" / script.name, script)
    root = tmp_path / "development/humanoid_repetitions3_20261024_v1"
    result = subprocess.run(["bash", str(script)], capture_output=True)
    assert result.returncode == 0 and not root.exists()
    seeds = (8113, 9281, 14423)
    for seed in seeds:
        path = root / f"seed_{seed}"
        path.mkdir(parents=True)
        (path / "manifest.json").write_text("{}")
    (root / "repetitions.json").write_text(json.dumps({"seeds": seeds}))
    fake = tmp_path / "bin/uv"
    fake.write_text(
        f"#!{sys.executable}\n"
        + """import json, os, sys
from pathlib import Path
a = sys.argv[1:]
with open(os.environ['MOCK_LOG'], 'a') as f: f.write(json.dumps(a)+'\\n')
if 'tools/humanoid_repetition_seeds.py' in a:
 root=Path(a[a.index('--root')+1])
 print('\\n'.join(map(str,json.loads((root/'repetitions.json').read_text())['seeds'])))
if '--campaign' in a:
 assert a[a.index('--max-new-attempts')+1] == '14'
 assert a[a.index('--max-new-afs-requests')+1] == '9'
 assert '--continue-after-exclusion' not in a
 if '9281' in a[a.index('--campaign')+1]: raise SystemExit(2)
if '--require-all' in a: raise SystemExit(2)
"""
    )
    fake.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    env = dict(
        os.environ, PATH=str(tmp_path / "bin") + os.pathsep + os.environ["PATH"], MOCK_LOG=str(log)
    )
    result = subprocess.run(["bash", str(script), "--live"], capture_output=True, env=env)
    assert result.returncode == 2
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert len([a for a in calls if "--campaign" in a]) == 3
    assert [Path(a[a.index("--campaign") + 1]).name for a in calls if "--campaign" in a] == [
        f"seed_{seed}" for seed in seeds
    ]
