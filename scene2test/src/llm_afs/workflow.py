"""Auditable single-round proposal -> scene compilation -> verified feedback import."""

import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import qmc

from procedural_world.export import export_bundle
from procedural_world.terrain import generate_course
from procedural_world.terrain_presets import apply_parameters
from simulation_server.worlds import validate_bundle

from .contracts import Config, Proposal, validate_proposal


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    with Path(path).open("x") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def demo_proposal(config: Config):
    """A deterministic fixture, explicitly NOT an LLM prediction or failure evidence."""
    return Proposal.model_validate(
        {
            "schema_version": "failure-space-proposal-v1",
            "base_scene_revision": generate_course(config.course).revision,
            "hypothesis": "OFFLINE FIXTURE: midpoint plumbing checks, not a prediction.",
            "ranges": [d.model_dump() for d in config.domains],
            "representatives": [
                {
                    "values": [
                        {"path": d.path, "value": (d.low + d.high) / 2} for d in config.domains
                    ]
                }
            ],
        }
    )


def compile_scenes(config, proposal, root, *, samples=2, seed=0):
    """Representatives plus Sobol samples. Scene seed stays fixed; no invalid resampling."""
    validate_proposal(config, proposal)
    if not 0 <= samples <= 32 or not 0 <= seed < 2**32:
        raise ValueError("samples [0,32], sampler seed [0,2**32)")
    base = generate_course(config.course)
    candidates = [
        ({v.path: v.value for v in c.values}, "representative") for c in proposal.representatives
    ]
    if samples:
        points = qmc.Sobol(len(proposal.ranges), scramble=True, seed=seed).random_base2(
            int(np.ceil(np.log2(samples)))
        )[:samples]
        for point in points:
            candidates.append(
                (
                    {
                        d.path: float(d.low + t * (d.high - d.low))
                        for d, t in zip(proposal.ranges, point)
                    },
                    "sobol_in_llm_space",
                )
            )
    rows, seen = [], set()
    for i, (values, source) in enumerate(candidates):
        row = {
            "name": f"candidate_{i:04d}",
            "index": i,
            "parameters": values,
            "sampler": source,
            "status": "INVALID_SCENE",
        }
        course = apply_parameters(config.course, values)
        row["course"] = course
        try:
            spec = generate_course(course)
            if (spec.spawn_xy, spec.goal_xy) != (base.spawn_xy, base.goal_xy):
                raise ValueError("fixed task endpoints would change")
            if spec.revision in seen:
                row.update(status="DUPLICATE_SCENE", revision=spec.revision)
            else:
                seen.add(spec.revision)
                bundle = export_bundle(spec, root / row["name"])
                validate_bundle(bundle, "sha256:" + spec.revision)
                row.update(
                    status="READY_FOR_TERRAIN_RUNNER",
                    bundle=str(bundle.resolve()),
                    revision=spec.revision,
                )
        except ValueError as exc:
            row["reason"] = str(exc)
        rows.append(row)
    suite = {
        "schema_version": "llm-afs-suite-v1",
        "config_sha256": digest(config.model_dump()),
        "proposal_sha256": digest(proposal.model_dump()),
        "seed": seed,
        "purpose": "candidate generation, NOT evaluated robot failures",
        "scenes": rows,
    }
    write(root / "suite.json", suite)
    return suite


def import_feedback(config, prior_run, summary_path):
    """Trusted local artifacts only. Recheck bundle/request/result hashes and condition identity.

    This detects accidental mixing/tampering, not a malicious local writer able to replace
    manifests. No unexecuted predictions become observations. Infra errors are separate.
    """
    prior_run, summary_path = Path(prior_run).resolve(), Path(summary_path).resolve()
    prior = read(prior_run / "context.json")
    protocol = read(prior_run / "protocol.json")
    if protocol["config_sha256"] != digest(config.model_dump()):
        raise ValueError("feedback config differs from current frozen config")
    if digest(prior) != protocol["context_sha256"]:
        raise ValueError("prior context checksum mismatch")
    suite = read(prior_run / "suite.json")
    if read(prior_run / "status.json")["suite_sha256"] != digest(suite):
        raise ValueError("prior suite checksum mismatch")
    runner_protocol = read(summary_path.parent / "protocol.json")
    if Path(runner_protocol["suite"]).resolve() != prior_run / "suite.json":
        raise ValueError("runner used another scene suite")
    task = config.task_spec
    if (
        runner_protocol["duration_s"] != task["maximum_duration_s"]
        or runner_protocol["speed_mps"] != task["speed_mps"]
    ):
        raise ValueError("runner duration/speed differs from frozen task")
    candidates = {
        (s["name"], s["index"]): s
        for s in suite["scenes"]
        if s["status"] == "READY_FOR_TERRAIN_RUNNER"
    }
    observations = list(prior["observations"])
    known = {o["job_id"] for o in observations}
    execution_signature = next(
        (o["execution_signature"] for o in observations if o.get("execution_signature")), None
    )
    for row in read(summary_path):
        candidate = candidates.get((row["name"], row["index"]))
        if candidate is None:
            raise ValueError("feedback candidate not in prior suite")
        job = Path(row["job"]).resolve()
        if job.parent != summary_path.parent:
            raise ValueError("unexpected job location")
        if job.name in known:
            raise ValueError("duplicate feedback job")
        known.add(job.name)
        spec = validate_bundle(Path(candidate["bundle"]), "sha256:" + candidate["revision"])
        request = read(job / "request.json")
        if request["resources"]["scene"] != {
            "id": spec.scene_id,
            "revision": "sha256:" + spec.revision,
        }:
            raise ValueError("feedback request scene mismatch")
        if request["task"] != {
            "schema": "navigation@1.0",
            "parameters": {"speed_mps": task["speed_mps"]},
        } or request["execution"] != {
            "seed": spec.config.seed,
            "maximum_duration_s": task["maximum_duration_s"],
            "physics_timestep_s": task["physics_timestep_s"],
            "settling_duration_s": task["settling_duration_s"],
        }:
            raise ValueError("feedback execution/task mismatch")
        observation = {
            "job_id": job.name,
            "parameters": candidate["parameters"],
            "scene_revision": spec.revision,
            "summary_sha256": digest(row),
        }
        if not (job / "execution_result.json").exists():
            if row["status"] != "EXECUTION_ERROR":
                raise ValueError("missing evaluated result")
            observation.update(
                status="EXECUTION_ERROR",
                robot_failure=None,
                reason="worker did not produce a result",
            )
            observations.append(observation)
            continue
        result = read(job / "execution_result.json")
        if result["job_id"] != job.name:
            raise ValueError("result job mismatch")
        artifacts = set()
        for a in result["artifacts"]:
            ident, name = a["artifact_id"].split(":", 1)
            if ident != job.name or Path(name).name != name or name in artifacts:
                raise ValueError("invalid artifact identity")
            artifacts.add(name)
            data = (job / name).read_bytes()
            if len(data) != a["size_bytes"] or hashlib.sha256(data).hexdigest() != a[
                "sha256"
            ].removeprefix("sha256:"):
                raise ValueError("feedback artifact checksum mismatch")
        if not {"reproduction.json", "scene_spec.json", "state_trajectory.jsonl"} <= artifacts:
            raise ValueError("missing required feedback artifacts")
        reproduction = read(job / "reproduction.json")
        if (
            reproduction["resolved_resources"] != request["resources"]
            or reproduction["scene_revision"] != spec.revision
            or digest(read(job / "scene_spec.json")) != digest(spec.to_dict())
        ):
            raise ValueError("feedback actual scene/resources mismatch")
        if reproduction["runtime"]["execution_provider"] != "CUDAExecutionProvider":
            raise ValueError("feedback requires verified CUDA execution")
        resources = {k: v for k, v in request["resources"].items() if k != "scene"}
        if (
            resources["robot"]["id"] != config.robot_spec["id"]
            or resources["policy"]["id"] != config.policy_spec["policy_id"]
        ):
            raise ValueError("feedback robot/policy mismatch")
        signature = digest(
            {
                "resources": resources,
                "code": reproduction["code_sha256"],
                "assets": reproduction["source_resource_sha256"],
                "metrics_version": reproduction["metrics_version"],
                "runtime": reproduction["runtime"],
            }
        )
        if execution_signature is not None and signature != execution_signature:
            raise ValueError("feedback mixes execution code/resources; start a new experiment")
        execution_signature = signature
        execution, facts = result["execution"], result["task_facts"]
        if facts != reproduction["task_facts"]:
            raise ValueError("result facts differ from verified reproduction")
        valid = execution["valid"] is True and execution["status"] == "SUCCEEDED"
        if valid and type(facts.get("navigation_success")) is not bool:
            raise ValueError("missing actual success fact")
        observation.update(
            status="EVALUATED" if valid else "INDETERMINATE",
            robot_failure=not facts["navigation_success"] if valid else None,
            reason=execution["termination_reason"],
            facts=facts,
            execution_signature=signature,
            result_sha256=digest(result),
        )
        observations.append(observation)
    # Explicit bound: do not silently discard observations to fit the prompt.
    if len(observations) > 64:
        raise ValueError("maximum 64 feedback observations; history selection not implemented")
    return observations
