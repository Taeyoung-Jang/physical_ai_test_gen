"""Prepare continuation after proven cancelled policy construction; no live execution."""

import json
import shutil
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
import run_robot_arm_free_pair_search as cli  # noqa: E402

from robot_arm import free_pair_search as experiment  # noqa: E402
from robot_arm import phase_measure, placement, search  # noqa: E402

TARGET = PROJECT / "experiments/robot_arm_libero/free_pair_continuation_v5"


def prepare(source, target):
    if target.exists():
        raise FileExistsError("continuation already prepared; preserve it")
    m = search.read(source / "manifest.json")
    if search.sha(source / "manifest.json") != (source / "manifest.sha256").read_text().strip():
        raise ValueError("original manifest changed")
    if m.get("mode") != experiment.VERSION or m.get("recovery"):
        raise ValueError("expected original free-pair campaign")
    design = experiment.validate(m["design"])
    c = design["experiment"]
    relative = f"seed_{c['seeds'][0]}/afs/attempt_00000"
    d = source / relative
    if sorted(str(p.relative_to(source)) for p in source.glob("seed_*/*/attempt_*")) != [relative]:
        raise ValueError("expected only first cancelled slot")
    if {p.name for p in d.iterdir()} != {
        "candidate.json",
        "manifest.json",
        "robot_intent.json",
        "run.log",
        "worker_started.json",
    }:
        raise ValueError("unexpected artifacts; rollout may have started")
    pid = search.read(d / "worker_started.json")["pid"]
    if type(pid) is not int or pid <= 0 or Path(f"/proc/{pid}").exists():
        raise ValueError("worker may still be running; no concurrent continuation")
    log = (d / "run.log").read_text()
    if not all(
        marker in log
        for marker in ["KeyboardInterrupt", "create_gr00t_sim_policy(", "import gr00t.model"]
    ):
        raise ValueError("no proof of cancellation during policy construction")
    value = experiment.candidate(
        design, experiment.uniform(design, c["seeds"][0], 0), c["seeds"][0], 0, "uniform bootstrap"
    )
    if search.read(d / "candidate.json") != value or search.read(d / "robot_intent.json") != value:
        raise ValueError("original candidate/intent mismatch")
    drift = [p for p, h in m["source_hashes"].items() if search.sha(p) != h]
    if any(p != str(PROJECT / "src/robot_arm/free_pair_search.py") for p in drift):
        raise ValueError("unreviewed source change")
    frozen = search.freeze(
        c,
        cli.sources(c)
        + [Path(__file__).resolve(), PROJECT / "tools/continue_robot_arm_free_pair.sh"],
    )
    if frozen["model_hashes"] != m["model_hashes"]:
        raise ValueError("model changed")
    files = [source / "manifest.json", source / "manifest.sha256"] + list(d.iterdir())
    if any(p.is_symlink() or not p.is_file() for p in files):
        raise ValueError("regular evidence files required")
    inherited = {str(p): search.sha(p) for p in files}
    target.mkdir(parents=True, exist_ok=False)
    dest = target / relative
    shutil.copytree(d, dest)
    assert all(search.sha(dest / p.name) == inherited[str(p)] for p in d.iterdir())
    result = {
        "status": "INCONCLUSIVE",
        "task_outcome": None,
        "reason": "preserved_pre_rollout_user_cancel",
        "administrative_record": True,
        "rollout_started": False,
        "source_directory": str(d),
        "claim": "Cancelled slot retained and consumed; no replay/replacement.",
    }
    placement.save(dest / "receipt.json", result)
    placement.save(dest / "measurement.json", phase_measure.case_measure(dest, result))
    experiment.seal(dest)
    remaining = len(c["seeds"]) * c["per_arm"] * 2 - 1
    recovery = {
        "version": "pre-rollout-cancel-continuation-v1",
        "source": str(source),
        "excluded_slots": {relative: search.sha(dest / "receipt.json")},
        "new_attempt_cap": remaining,
        "source_changes": drift,
        "comparison_limit": "One AFS slot excluded; equal-valid Gain unavailable "
        "without a separately approved design.",
    }
    frozen.update(
        mode=experiment.VERSION, design=design, recovery=recovery, inherited_artifacts=inherited
    )
    placement.save(target / "manifest.json", frozen)
    (target / "manifest.sha256").write_text(search.sha(target / "manifest.json") + "\n")
    placement.save(target / "recovery.json", recovery)
    return recovery


if __name__ == "__main__":
    print(json.dumps(prepare(cli.ROOT.resolve(), TARGET.resolve()), indent=2))
