"""Explicit audited development fork of an excluded independent evaluation.

No API/robot during preparation. Original checkpoints and budgets are never edited.
Policy changes after seeing results mean this is NOT the original prospective evaluation.
"""

import fcntl
import json
import shutil
import sqlite3
import tempfile
from contextlib import closing
from copy import deepcopy
from pathlib import Path

from failure_client.evaluation.behavior_measures import verify_episode_files
from failure_client.evaluation.goal_run_reader import _hash_file, read_json
from failure_client.evaluation.research_records import EpisodeRecord
from failure_client.storage.research_store import ResearchStore
from llm_afs.behavior import digest

from .discovery_evaluation import EvaluationDesign, evaluation_fingerprint
from .independent_discovery import (
    MODE as INDEPENDENT_MODE,
)
from .independent_discovery import (
    DiscoveryEvaluation,
    IndependentSeed,
    checked_manifest,
)
from .local_goal_adapter import atomic_json
from .research_protocol import CampaignConfig

MODE = "operator-assisted-discovery-v1"
MANIFEST = "assisted-discovery-manifest-v1"
CLAIM = "operator_assisted_development_continuation_not_prospective_evaluation"
MIGRATION_FILES = {
    "src/failure_client/experiments/afs_autonomous.py",
    "src/failure_client/experiments/discovery_evaluation.py",
    "src/failure_client/experiments/independent_discovery.py",
    "src/failure_client/experiments/discovery_continuation.py",
    "src/failure_client/methods/autonomous_feedback.py",
    "src/failure_client/methods/behavior_feedback.py",
    "src/failure_client/methods/branch_anchors.py",
    "src/failure_client/methods/failure_objective.py",
    "src/llm_afs/behavior_request.py",
    "tools/run_discovery_evaluation.py",
    "tools/run_discovery_continuation.py",
}


def snapshot(root):
    """Read an existing SQLite store without creating DB tables or lock files."""
    # A read-only connection may create WAL/SHM sidecars. Query a private copy.
    with tempfile.TemporaryDirectory(prefix="discovery-continuation-snapshot-") as temp:
        target = Path(temp) / "campaign.sqlite3"
        shutil.copyfile(root / target.name, target)
        if (root / "campaign.sqlite3-wal").exists():
            shutil.copyfile(root / "campaign.sqlite3-wal", Path(temp) / "campaign.sqlite3-wal")
        with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM research_state WHERE id=1").fetchone()
            ledger = [
                dict(r) for r in db.execute("SELECT * FROM research_ledger ORDER BY revision")
            ]
    if row is None:
        raise ValueError("source campaign is not initialized")
    state = json.loads(row["payload"])
    if (
        digest(state) != row["sha256"]
        or not ledger
        or (
            ledger[-1]["revision"] != row["revision"] or ledger[-1]["state_sha256"] != row["sha256"]
        )
    ):
        raise ValueError("source checkpoint/ledger mismatch")
    return {"state": state, "ledger": ledger, "revision": row["revision"]}


class DevelopmentSeed(IndependentSeed):
    mode = MODE
    request_policy = "autonomous_development_endpoint"

    def _verify_lock(self):
        super()._verify_lock()
        campaign = self.root.parents[1]
        audit = read_json(campaign / "continuation.json")
        if digest(audit) != self.plan.get("continuation_sha256") or audit.get("claim") != CLAIM:
            raise ValueError("development continuation audit changed")
        for name, sha in audit["snapshot_digests"].items():
            if digest(read_json(campaign / name)) != sha:
                raise ValueError("continuation source snapshot changed")
        original = read_json(campaign / "source" / "seeds" / str(self.plan["seed"]) / "state.json")
        for key in ("attempts", "proposals"):
            if self.state[key][: len(original[key])] != original[key]:
                raise ValueError("preserved attempts/proposals changed")

    def _selection(self):
        candidate, ctx = super()._selection()
        if ctx is not None:
            ctx["development_continuation"] = {
                "claim": CLAIM,
                "source_manifest_sha256": self.plan["source_manifest_sha256"],
                "preserved_attempts": self.plan["preserved_attempts"],
                "preserved_afs_requests": self.plan["preserved_afs_requests"],
                "budget_reset": False,
            }
            ctx["failure_objective"]["scope"] = (
                "Same seed's preserved and new development observations; policy changed after "
                "inspection, NOT the original independent evaluation or a Gain estimate"
            )
        return candidate, ctx

    def summary(self):
        result = super().summary()
        n, p = self.plan["preserved_attempts"], self.plan["preserved_afs_requests"]
        result.update(
            claim=CLAIM,
            preserved_attempts=n,
            preserved_afs_requests=p,
            post_continuation_attempts=len(self.state["attempts"]) - n,
            post_continuation_afs_requests=len(self.state["proposals"]) - p,
            attempts_remaining=max(0, self.budget.max_attempts - len(self.state["attempts"])),
            budget_reset=False,
            limits=[
                CLAIM,
                "Preserved and post-continuation observations are development evidence, "
                "not a completed prospective evaluation",
                *[line for line in result["limits"] if "all new valid episodes" not in line],
            ],
        )
        metrics = result.pop("new_only_discovery_metrics")
        result["cumulative_development_metrics"] = metrics
        from failure_client.evaluation.taxonomy_profiles import metric_options
        from failure_client.reporting.discovery_metrics import calculate_discovery_metrics

        result["post_continuation_metrics"] = calculate_discovery_metrics(
            self.evaluation_records()[n:],
            **metric_options(self.cfg.scene_schema, self.budget.taxonomy_profile),
        )
        return result


class DevelopmentContinuation(DiscoveryEvaluation):
    mode = MODE
    seed_type = DevelopmentSeed

    @staticmethod
    def check_manifest(wrapped):
        manifest = checked_manifest(wrapped, schema_version=MANIFEST)
        if manifest.get("claim") != CLAIM:
            raise ValueError("development continuation claim required")
        return manifest

    @classmethod
    def create(cls, *args, **kwargs):
        raise ValueError("use explicit prepare_continuation, never an empty development reset")

    def summary(self):
        result = super().summary()
        result.update(
            claim=CLAIM,
            evaluation_complete=False,
            development_complete=result["status"] == "COMPLETE",
            joint_target_at_complete_budget=None,
            limits=[CLAIM, *result["limits"]],
        )
        return result


def prepare_continuation(source, output, *, apply=False, fingerprint_fn=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    if (
        output.exists()
        or output.is_symlink()
        or source.is_relative_to(output)
        or output.is_relative_to(source)
    ):
        raise ValueError("new disjoint output directory required")
    # Existing campaign execution lock, opened read-only: no new file in source.
    with (source / ".campaign.lock").open("r") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("source campaign is active") from None
        wrapped = read_json(source / "manifest.json")
        manifest = checked_manifest(wrapped)
        design = EvaluationDesign.model_validate(manifest["design"])
        if design.search.anchor_policy != "pass-control-v3":
            raise ValueError("only the original PASS-control policy may be continued")
        top = snapshot(source)
        if top["state"] != {"manifest_sha256": wrapped["sha256"], "mode": INDEPENDENT_MODE}:
            raise ValueError("source campaign manifest binding changed")
        env = (fingerprint_fn or evaluation_fingerprint)(
            CampaignConfig.model_validate(manifest["robot_config"])
        )
        previous = manifest["environment"]
        if {k: v for k, v in env.items() if k != "source_hashes"} != {
            k: v for k, v in previous.items() if k != "source_hashes"
        }:
            raise ValueError("robot resources/runtime drift cannot be continued")
        changes = {
            k: {"before": previous["source_hashes"].get(k), "after": env["source_hashes"].get(k)}
            for k in previous["source_hashes"].keys() | env["source_hashes"].keys()
            if previous["source_hashes"].get(k) != env["source_hashes"].get(k)
        }
        if set(changes) - MIGRATION_FILES or any(v["after"] is None for v in changes.values()):
            raise ValueError("unrelated source drift cannot be continued")
        snapshots = {
            "source/manifest.json": wrapped,
            "source/campaign_state.json": top["state"],
            "source/campaign_ledger.json": top["ledger"],
        }
        originals = {}
        excluded = 0
        for seed in design.seeds:
            seed_root = source / "seeds" / str(seed)
            snap = snapshot(seed_root)
            state = snap["state"]
            plan = state["lock"]["plan"]
            protocol = read_json(seed_root / "protocol.json")
            if protocol != {"lock": state["lock"], "lock_sha256": digest(state["lock"])} or state[
                "lock_sha256"
            ] != digest(state["lock"]):
                raise ValueError("source seed protocol/checkpoint mismatch")
            if (
                state["schema_version"] != INDEPENDENT_MODE
                or plan["mode"] != INDEPENDENT_MODE
                or plan["seed"] != seed
                or plan["history"]
                or plan["manifest_sha256"] != wrapped["sha256"]
                or plan["budget"] != manifest["design"]["search"]
                or plan["target_config"] != manifest["robot_config"]
                or state["lock"]["environment"] != previous
                or plan["condition_id"] != manifest["reference_condition_id"]
                or plan["geometry_id"] != manifest["reference_geometry_id"]
                or plan["execution_origin"] != manifest["execution_origin"]
                or plan["cold_start_per_seed"] != design.cold_start_per_seed
                or state["pending"] is not None
                or state["selected"] is not None
                or state["status"]
                not in {"READY", "NEEDS_ATTENTION", "COMPLETE", "COMPLETE_WITH_EXCLUSIONS"}
                or (state["status"] == "NEEDS_ATTENTION" and state["reason"] != "excluded_rollout")
                or len(state["attempts"]) > design.attempts_per_seed
                or len(state["proposals"]) > design.afs_requests_per_seed
            ):
                raise ValueError(
                    "source is not a completed-observation seed with unchanged settings"
                )
            for a in state["attempts"]:
                if "episode" not in a or "receipt" not in a:
                    raise ValueError("ambiguous rollout cannot be continued")
                row = EpisodeRecord.model_validate(a["episode"])
                raw = EpisodeRecord.model_validate(a["raw_episode"])
                verify_episode_files(raw)
                if (row.status, row.task_outcome, row.termination_reason, row.evidence_id) != (
                    raw.status,
                    raw.task_outcome,
                    raw.termination_reason,
                    raw.evidence_id,
                ):
                    raise ValueError("source outcome differs from verified raw execution")
                if row.source.path != str(seed_root / "attempts" / a["id"] / "rollout"):
                    raise ValueError("source seed contains external episode paths")
                if raw.status == "VALID" and (
                    raw.condition_id != plan["condition_id"]
                    or raw.policy_origin != plan["execution_origin"]
                ):
                    raise ValueError("source rollout condition/origin mismatch")
                if row.status == "INCONCLUSIVE":
                    if (
                        raw.status != "INCONCLUSIVE"
                        or raw.termination_reason != "api_timeout"
                        or (
                            a["receipt"].get("returncode") != 0
                            or a["receipt"].get("interrupted") is not None
                        )
                    ):
                        raise ValueError(
                            "only reviewed completed API-timeout exclusions may continue"
                        )
                    excluded += 1
            for p in state["proposals"]:
                if not ("candidate" in p or "rejection" in p):
                    raise ValueError("ambiguous proposal cannot be continued")
                for name, sha in p["artifacts"].items():
                    if _hash_file(seed_root / "proposals" / p["id"] / name) != sha:
                        raise ValueError("source proposal artifact changed")
            originals[seed] = state
            for name, value in (
                ("state", state),
                ("ledger", snap["ledger"]),
                ("protocol", protocol),
            ):
                snapshots[f"source/seeds/{seed}/{name}.json"] = value
        if not excluded:
            raise ValueError("reviewed excluded rollout required; not a generic source migration")
        new_manifest = deepcopy(manifest)
        new_manifest.update(schema_version=MANIFEST, environment=env, claim=CLAIM)
        new_budget = design.search.model_copy(update={"anchor_policy": "failure-diversity-v4"})
        new_manifest["design"]["search"] = new_budget.model_dump()
        audit = {
            "schema_version": "discovery-policy-continuation-v1",
            "claim": CLAIM,
            "source": str(source),
            "source_manifest_sha256": wrapped["sha256"],
            "source_revision": top["revision"],
            "source_changes": changes,
            "snapshot_digests": {k: digest(v) for k, v in snapshots.items()},
            "budget_reset": False,
            "api_calls": 0,
            "robot_launched": False,
            "preserved": {
                str(seed): {"attempts": len(s["attempts"]), "afs_requests": len(s["proposals"])}
                for seed, s in originals.items()
            },
        }
        new_manifest["continuation_sha256"] = digest(audit)
        new_wrapped = {"manifest": new_manifest, "sha256": digest(new_manifest)}
        DevelopmentContinuation.check_manifest(new_wrapped)
        previews = {}
        for seed, old in originals.items():
            scratch = object.__new__(DevelopmentSeed)
            scratch.root = source / "seeds" / str(seed)
            scratch.state = deepcopy(old)
            scratch.state["lock"]["plan"].update(
                mode=MODE,
                budget=new_budget.model_dump(),
                source_manifest_sha256=wrapped["sha256"],
                preserved_attempts=len(old["attempts"]),
                preserved_afs_requests=len(old["proposals"]),
            )
            candidate, ctx = scratch._selection()
            previews[str(seed)] = {
                "local_cold_start_pending": candidate is not None,
                "allowed_intents": ctx["failure_objective"]["allowed_intents"] if ctx else [],
                "excluded_scenes_not_replayed": len(ctx.get("excluded_scene_parameters", []))
                if ctx
                else 0,
            }
        remaining = {
            str(seed): {
                "attempts": design.attempts_per_seed - len(s["attempts"]),
                "afs_requests": design.afs_requests_per_seed - len(s["proposals"]),
                "valid_needed": design.valid_per_seed
                - sum(a["episode"]["status"] == "VALID" for a in s["attempts"]),
            }
            for seed, s in originals.items()
        }
        for row in manifest["control_provenance"]:
            p = Path(row["source"]["path"]).resolve()
            if output.is_relative_to(p) or p.is_relative_to(output):
                raise ValueError("output overlaps control archives")
        if apply:
            output.mkdir(parents=True, exist_ok=False)
            for name, value in snapshots.items():
                atomic_json(output / name, value)
            atomic_json(output / "continuation.json", audit)
            atomic_json(output / "manifest.json", new_wrapped)
            for seed, old in originals.items():
                state = deepcopy(old)
                plan = state["lock"]["plan"]
                plan.update(
                    mode=MODE,
                    budget=new_budget.model_dump(),
                    manifest_sha256=new_wrapped["sha256"],
                    continuation_sha256=digest(audit),
                    source_manifest_sha256=wrapped["sha256"],
                    preserved_attempts=len(old["attempts"]),
                    preserved_afs_requests=len(old["proposals"]),
                )
                state["lock"]["environment"] = env
                state.update(schema_version=MODE, lock_sha256=digest(state["lock"]))
                target = output / "seeds" / str(seed)
                target.mkdir(parents=True, exist_ok=False)
                if (source / "seeds" / str(seed) / "proposals").exists():
                    shutil.copytree(
                        source / "seeds" / str(seed) / "proposals", target / "proposals"
                    )
                atomic_json(
                    target / "protocol.json",
                    {"lock": state["lock"], "lock_sha256": state["lock_sha256"]},
                )
                ResearchStore(target).save(
                    state, -1, "operator_assisted_continuation", audit["preserved"][str(seed)]
                )
            ResearchStore(output).save(
                {"manifest_sha256": new_wrapped["sha256"], "mode": MODE},
                -1,
                "operator_assisted_continuation",
            )
        return {
            "applied": apply,
            "output": str(output),
            "claim": CLAIM,
            "audit": audit,
            "remaining": remaining,
            "next_selection": previews,
        }
