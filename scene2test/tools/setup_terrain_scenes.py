"""Generate configurable terrain bundles and record invalid proposals without resampling."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml
from scipy.stats import qmc

from procedural_world.export import export_bundle
from procedural_world.terrain import generate_course
from procedural_world.terrain_presets import PRESETS, apply_parameters, preset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", choices=[*PRESETS, "all"], default="mixed")
    parser.add_argument("--config", type=Path, help="YAML with course and optional parameters")
    parser.add_argument("--n", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--sampler", choices=["random", "sobol"], default="sobol")
    parser.add_argument("--render", action="store_true")
    parser.add_argument(
        "--output-root", type=Path, default=Path("/workspace/g1_failure/runtime/terrain_scenes")
    )
    args = parser.parse_args()
    if not 1 <= args.n <= 256 or args.seed < 0:
        parser.error("n must be [1,256], seed nonnegative")
    document = yaml.safe_load(args.config.read_text()) if args.config else None
    if document is not None and (
        not isinstance(document, dict) or set(document) - {"course", "parameters"}
    ):
        parser.error("config supports only course and parameters")
    names = ["configured"] if document else list(PRESETS) if args.preset == "all" else [args.preset]
    run = args.output_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    run.mkdir(parents=True, exist_ok=False)
    print(f"SCENE_SUITE={run}", flush=True)
    rows = []
    for name in names:
        base = document["course"] if document else preset(name, args.seed)
        domains = document.get("parameters", {}) if document else {}
        keys = sorted(domains)
        for key in keys:
            entry = domains[key]
            if set(entry) != {"low", "high", "type"} or entry["type"] not in {"float", "int"}:
                raise ValueError("domains require low/high/type (float or int)")
            if not np.isfinite([entry["low"], entry["high"]]).all() or entry["low"] > entry["high"]:
                raise ValueError("invalid parameter range")
            if entry["type"] == "int" and any(type(entry[k]) is not int for k in ("low", "high")):
                raise ValueError("integer domain endpoints must be integers")
        dim = max(1, len(keys))
        if args.sampler == "sobol":
            points = qmc.Sobol(dim, scramble=True, seed=args.seed).random_base2(
                int(np.ceil(np.log2(args.n)))
            )[: args.n]
        else:
            points = np.random.default_rng(args.seed).random((args.n, dim))
        for i, point in enumerate(points):
            parameters = {}
            for j, key in enumerate(keys):
                d = domains[key]
                parameters[key] = (
                    int(d["low"] + np.floor(point[j] * (d["high"] - d["low"] + 1)))
                    if d["type"] == "int"
                    else float(d["low"] + point[j] * (d["high"] - d["low"]))
                )
            course = apply_parameters(base, parameters)
            course["seed"] = args.seed + i
            row = {
                "name": name,
                "index": i,
                "parameters": parameters,
                "course": course,
                "sampler": args.sampler,
                "status": "INVALID_SCENE",
            }
            try:
                spec = generate_course(course)
                parent = run / f"{name}_{i:04d}"
                bundle = export_bundle(spec, parent, render=args.render)
                (bundle.parent / "recipe.yaml").write_text(
                    yaml.safe_dump({"course": course}, sort_keys=False)
                )
                row.update(
                    status="READY_FOR_TERRAIN_RUNNER", bundle=str(bundle), revision=spec.revision
                )
            except ValueError as exc:
                row["reason"] = str(exc)
            rows.append(row)
            (run / "suite.json").write_text(
                json.dumps({"config": document, "seed": args.seed, "scenes": rows}, indent=2) + "\n"
            )
            print(json.dumps({k: row[k] for k in ("name", "index", "status")}), flush=True)
    print(f"INDEX={run / 'suite.json'}", flush=True)


if __name__ == "__main__":
    main()
