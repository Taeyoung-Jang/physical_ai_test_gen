"""Versioned, bounded mixed-type terrain spaces; no robot or generator code mutation."""

import copy
import math
from typing import Any, Literal

import numpy as np
from pydantic import Field, model_validator

from procedural_world.core import scene_graph
from procedural_world.export import export_bundle
from procedural_world.terrain import generate_course
from procedural_world.terrain_presets import apply_parameters
from simulation_server.worlds import validate_bundle

from .contracts import Config, StrictModel
from .workflow import digest, import_feedback, read, write


class Domain(StrictModel):
    path: str
    kind: Literal["float", "int", "choice"]
    low: float | None
    high: float | None
    choices: list[str]

    @model_validator(mode="after")
    def valid(self):
        if self.kind == "choice":
            if self.low is not None or self.high is not None or not self.choices:
                raise ValueError("choice requires choices and null bounds")
            if len(set(self.choices)) != len(self.choices):
                raise ValueError("duplicate choices")
        elif self.low is None or self.high is None or self.low > self.high or self.choices:
            raise ValueError("numeric domain requires ordered bounds and empty choices")
        elif self.kind == "int" and (self.low != int(self.low) or self.high != int(self.high)):
            raise ValueError("integer bounds required")
        return self

    def sample(self, u):
        if self.kind == "choice":
            return self.choices[min(int(u * len(self.choices)), len(self.choices) - 1)]
        if self.kind == "int":
            return min(int(self.high), int(self.low) + int(u * (self.high - self.low + 1)))
        return float(self.low + u * (self.high - self.low))


class Layout(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    course: dict[str, Any]
    domains: list[Domain] = Field(min_length=1, max_length=48)


class ExpandedConfig(StrictModel):
    schema_version: Literal["expanded-afs-config-v2"]
    condition: Config
    endpoint_policy: Literal["fixed", "generated_course_end"]
    layouts: list[Layout] = Field(min_length=1, max_length=16)

    @property
    def task_spec(self):
        return self.condition.task_spec

    @property
    def robot_spec(self):
        return self.condition.robot_spec

    @property
    def policy_spec(self):
        return self.condition.policy_spec

    @model_validator(mode="after")
    def valid(self):
        if len({x.name for x in self.layouts}) != len(self.layouts):
            raise ValueError("duplicate layout name")
        for layout in self.layouts:
            base = generate_course(layout.course)
            if self.endpoint_policy == "fixed":
                reference = generate_course(self.condition.course)
                if (base.spawn_xy, base.goal_xy) != (reference.spawn_xy, reference.goal_xy):
                    raise ValueError("layout changes fixed endpoints")
            if len({d.path for d in layout.domains}) != len(layout.domains):
                raise ValueError("duplicate domain path")
            for d in layout.domains:
                parts = d.path.split(".")
                value = layout.course
                try:
                    for part in parts:
                        value = value[int(part)] if isinstance(value, list) else value[part]
                except (KeyError, IndexError, ValueError, TypeError):
                    raise ValueError("domain must reference an explicit existing field") from None
                allowed = d.path in {"seed", "width_m", "friction"}
                if len(parts) in (3, 4) and parts[0] == "segments":
                    kind = layout.course["segments"][int(parts[1])]["kind"]
                    fields = {
                        "flat": {"length_m"},
                        "friction": {"length_m"},
                        "ramp": {"length_m", "angle_deg", "landing_m"},
                        "stairs": {"step_height_m", "tread_m", "count", "landing_m"},
                        "rough": {"length_m", "amplitude_m", "cell_length_m"},
                        "bottleneck": {"length_m", "gap_m"},
                        "obstacles": {"length_m", "count", "pattern"},
                    }
                    allowed = len(parts) == 3 and parts[2] in fields[kind] | {"width_m", "friction"}
                    allowed |= (
                        kind == "obstacles"
                        and len(parts) == 4
                        and parts[2] in {"size_min_m", "size_max_m"}
                        and parts[3] in {"0", "1", "2"}
                    )
                if not allowed:
                    raise ValueError("field is not a controllable scene factor")
                expected = (
                    "choice" if isinstance(value, str) else "int" if type(value) is int else "float"
                )
                if d.path == "seed" or parts[-1] == "count":
                    expected = "int"
                elif expected == "int":
                    expected = "float"  # YAML may spell a continuous value as an integer.
                if d.kind != expected:
                    raise ValueError("domain type does not match field")
                if d.kind == "choice":
                    if not set(d.choices) <= {"random", "slalom"} or value not in d.choices:
                        raise ValueError("unsupported pattern")
                elif not d.low <= value <= d.high:
                    raise ValueError("base value outside domain")
                if d.path == "seed" and not 0 <= d.low <= d.high < 2**32:
                    raise ValueError("scene seed outside uint32")
        return self


class Space(StrictModel):
    layout: str
    hypothesis: str = Field(min_length=1, max_length=2000)
    domains: list[Domain] = Field(min_length=1, max_length=48)


class ExpandedProposal(StrictModel):
    schema_version: Literal["failure-space-proposal-v2"]
    config_sha256: str
    spaces: list[Space] = Field(min_length=1, max_length=16)


def validate_proposal(config, proposal):
    if proposal.config_sha256 != digest(config.model_dump()):
        raise ValueError("proposal config identity mismatch")
    layouts = {x.name: x for x in config.layouts}
    for space in proposal.spaces:
        if space.layout not in layouts:
            raise ValueError("unknown layout")
        allowed = {d.path: d for d in layouts[space.layout].domains}
        if len({d.path for d in space.domains}) != len(space.domains):
            raise ValueError("duplicate proposed domain")
        for d in space.domains:
            parent = allowed.get(d.path)
            if parent is None or parent.kind != d.kind:
                raise ValueError("unknown path/type")
            if d.kind == "choice":
                if not set(d.choices) <= set(parent.choices):
                    raise ValueError("choice exceeds allowed domain")
            elif not parent.low <= d.low <= d.high <= parent.high:
                raise ValueError("proposal exceeds allowed bounds")


def demo(config):
    return ExpandedProposal(
        schema_version="failure-space-proposal-v2",
        config_sha256=digest(config.model_dump()),
        spaces=[
            Space(
                layout=x.name, hypothesis="OFFLINE fixture; not failure evidence", domains=x.domains
            )
            for x in config.layouts
        ],
    )


def context(config, observations):
    return {
        "config": config.model_dump(),
        "config_sha256": digest(config.model_dump()),
        "observations": observations,
        "layouts": [
            {
                "name": x.name,
                "scene_graph": scene_graph(generate_course(x.course)).to_dict(),
                "base_revision": generate_course(x.course).revision,
            }
            for x in config.layouts
        ],
        "endpoint_semantics": config.endpoint_policy,
        "constraints": [
            "Only approved layouts and typed bounds; no code/XML output",
            "Robot/policy/evaluator unchanged; geometry rejection is not robot failure",
            "generated_course_end explicitly follows the end of each generated course",
            "Host reserves exploration outside proposed spaces; hypotheses are not facts",
        ],
    }


def feedback(config, prior_run, summary_path):
    observations = import_feedback(config, prior_run, summary_path)
    suite = read(prior_run / "suite.json")
    candidates = {(r["name"], r["index"]): r for r in suite["scenes"]}
    by_job = {
        r["job"].rstrip("/").split("/")[-1]: candidates[(r["name"], r["index"])]
        for r in read(summary_path)
        if (r["name"], r["index"]) in candidates
    }
    for observation in observations:
        candidate = by_job.get(observation["job_id"])
        if candidate:
            observation["layout"] = candidate["layout"]
            observation["strategy"] = candidate["sampler"]
    return observations


def compile_scenes(config, proposal, root, *, samples=12, seed=0, observations=(), mode="mixed"):
    """Fixed attempt budget, never resample invalids. Mixed quotas: new 1/2, LLM 1/4, local 1/4.

    All axes sampled jointly so interactions are executable, not inferred independent effects.
    Local search uses verified failure neighborhoods only; no local failure -> new exploration.
    """
    validate_proposal(config, proposal)
    if not 1 <= samples <= 256 or not 0 <= seed < 2**32 or mode not in {"mixed", "random", "sobol"}:
        raise ValueError("invalid sampling budget/seed/mode")
    from scipy.stats import qmc

    rng = np.random.default_rng(seed)
    layouts = {x.name: x for x in config.layouts}
    # One Sobol stream per dimensionality/layout avoids padding or mixing dimensions.
    streams = {
        x.name: qmc.Sobol(len(x.domains), scramble=True, seed=seed + i).random_base2(
            math.ceil(math.log2(samples))
        )
        for i, x in enumerate(config.layouts)
    }
    counters = dict.fromkeys(layouts, 0)
    failures = [
        o
        for o in observations
        if o.get("robot_failure") is True
        and o.get("status") == "EVALUATED"
        and o.get("execution_signature")
        and o.get("layout") in layouts
    ]
    seen = {o["scene_revision"].removeprefix("sha256:") for o in observations}
    rows = []
    exploration_index = 0
    for i in range(samples):
        strategy, parent, overrides = "new_space", None, {}
        layout = config.layouts[exploration_index % len(config.layouts)]
        if mode == "mixed" and i % 4 == 2:
            space = proposal.spaces[(i // 4) % len(proposal.spaces)]
            layout, strategy = layouts[space.layout], "llm_joint_space"
            overrides = {d.path: d for d in space.domains}
        elif mode == "mixed" and i % 4 == 3 and failures:
            parent = failures[int(rng.integers(len(failures)))]
            layout, strategy = layouts[parent["layout"]], "failure_neighborhood"
        if strategy == "new_space":
            exploration_index += 1
        u = (
            streams[layout.name][counters[layout.name]]
            if mode == "sobol"
            else rng.random(len(layout.domains))
        )
        counters[layout.name] += 1
        values = {}
        for d, t in zip(layout.domains, u):
            domain = overrides.get(d.path, d)
            if parent and d.kind != "choice" and d.path != "seed":
                center = parent["parameters"][d.path]
                radius = max(1 if d.kind == "int" else 0, (d.high - d.low) * 0.15)
                low, high = max(d.low, center - radius), min(d.high, center + radius)
                if d.kind == "int":
                    low, high = math.ceil(low), math.floor(high)
                domain = d.model_copy(update={"low": low, "high": high})
            values[d.path] = domain.sample(t)
        row = {
            "name": f"candidate_{i:04d}",
            "index": i,
            "layout": layout.name,
            "parameters": values,
            "sampler": strategy if mode == "mixed" else mode,
            "parent_failure_job": parent["job_id"] if parent else None,
            "status": "INVALID_SCENE",
        }
        try:
            course = apply_parameters(copy.deepcopy(layout.course), values)
            row["course"] = course
            spec = generate_course(course)
            if config.endpoint_policy == "fixed":
                base = generate_course(config.condition.course)
                if (spec.spawn_xy, spec.goal_xy) != (base.spawn_xy, base.goal_xy):
                    raise ValueError("candidate changes fixed endpoints")
            row.update(revision=spec.revision, spawn_xy=spec.spawn_xy, goal_xy=spec.goal_xy)
            if spec.revision in seen:
                row["status"] = "DUPLICATE_SCENE"
            else:
                bundle = export_bundle(spec, root / row["name"])
                validate_bundle(bundle, "sha256:" + spec.revision)
                seen.add(spec.revision)
                row.update(status="READY_FOR_TERRAIN_RUNNER", bundle=str(bundle.resolve()))
        except ValueError as exc:
            row["reason"] = str(exc)
        rows.append(row)
    suite = {
        "schema_version": "llm-afs-suite-v2",
        "config_sha256": digest(config.model_dump()),
        "proposal_sha256": digest(proposal.model_dump()),
        "seed": seed,
        "endpoint_policy": config.endpoint_policy,
        "attempt_budget": samples,
        "purpose": "unevaluated candidates; NOT failure evidence or equal valid-rollout comparison",
        "scenes": rows,
    }
    write(root / "suite.json", suite)
    return suite
