"""GPT-6 terrain space proposer. Default: prepare request only, zero API/GPU calls."""

import argparse
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from llm_afs import contracts, provider, workflow
from llm_afs.contracts import Config, Proposal, context, proposal_schema, validate_proposal
from llm_afs.workflow import compile_scenes, demo_proposal, digest, import_feedback, read, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/llm_afs_terrain.yaml"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="explicit opt-in: ONE paid API call")
    mode.add_argument("--offline-demo", action="store_true", help="deterministic fixture, NOT LLM")
    mode.add_argument("--proposal-file", type=Path, help="replay a saved proposal, no API")
    parser.add_argument("--feedback", nargs=2, type=Path, metavar=("PRIOR_RUN", "SUMMARY"))
    parser.add_argument("--samples", type=int, default=2, help="extra Sobol samples [0,32]")
    parser.add_argument("--seed", type=int, default=0, help="sampler seed; scene seed stays fixed")
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument(
        "--output-root", type=Path, default=Path("/workspace/g1_failure/runtime/llm_afs")
    )
    args = parser.parse_args()
    if not 0 <= args.samples <= 32 or not 0 <= args.seed < 2**32:
        parser.error("samples [0,32], seed [0,2**32)")
    config = Config.model_validate(yaml.safe_load(args.config.read_text()))
    observations = import_feedback(config, *args.feedback) if args.feedback else []
    ctx = context(config, observations)
    ctx["proposal_budget"] = {
        "additional_sobol_samples": args.samples,
        "maximum_representatives": 8,
        "maximum_api_calls_this_run": 1,
    }
    body = provider.request_body(
        ctx, proposal_schema(config), max_output_tokens=args.max_output_tokens
    )
    root = args.output_root.resolve() / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    root.mkdir(parents=True, exist_ok=False)
    print(f"LLM_AFS_RUN={root}", flush=True)
    origin = (
        "openai_api"
        if args.live
        else "offline_fixture"
        if args.offline_demo
        else "proposal_file"
        if args.proposal_file
        else "request_only"
    )
    write(root / "config.json", config.model_dump())
    write(root / "context.json", ctx)
    write(root / "request.json", body)
    write(
        root / "protocol.json",
        {
            "schema_version": "llm-afs-round-v1",
            "origin": origin,
            "model": provider.MODEL,
            "prompt_version": provider.PROMPT_VERSION,
            "config_sha256": digest(config.model_dump()),
            "context_sha256": digest(ctx),
            "request_sha256": digest(body),
            "code_sha256": {
                str(Path(m.__file__).name): hashlib.sha256(
                    Path(m.__file__).read_bytes()
                ).hexdigest()
                for m in (contracts, provider, workflow)
            },
            "cli_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "feedback_source": [str(p.resolve()) for p in args.feedback] if args.feedback else None,
            "seed": args.seed,
            "additional_samples": args.samples,
            "executes_robot": False,
        },
    )
    if origin == "request_only":
        write(root / "status.json", {"status": "REQUEST_PREPARED", "api_calls": 0})
        print("Request prepared. No API or GPU call. Review context.json before --live.")
        return
    started = time.monotonic()
    try:
        if args.live:
            response = provider.call(body)
            write(root / "api_response.json", response)
            raw = provider.extract_proposal(response)
        elif args.offline_demo:
            raw = demo_proposal(config).model_dump()
        else:
            raw = read(args.proposal_file)
        write(root / "raw_proposal.json", raw)
        proposal = validate_proposal(config, Proposal.model_validate(raw))
        write(root / "proposal.json", proposal.model_dump())
        suite = compile_scenes(config, proposal, root, samples=args.samples, seed=args.seed)
        ready = sum(s["status"] == "READY_FOR_TERRAIN_RUNNER" for s in suite["scenes"])
        write(
            root / "status.json",
            {
                "status": "SCENES_READY" if ready else "NO_VALID_SCENES",
                "origin": origin,
                "ready_scenes": ready,
                "suite_sha256": digest(suite),
                "valid_robot_rollouts": 0,
                "elapsed_seconds": time.monotonic() - started,
            },
        )
        print(f"SUITE={root / 'suite.json'}; ready={ready}; origin={origin}")
        if not ready:
            raise SystemExit(2)
    except Exception as exc:
        # No SDK/http exception repr or environment values written to logs.
        write(
            root / "status.json",
            {
                "status": "ERROR",
                "error_type": type(exc).__name__,
                "elapsed_seconds": time.monotonic() - started,
            },
        )
        print(f"Stopped: {type(exc).__name__}. Artifacts preserved at {root}.")
        if isinstance(exc, (ValueError, RuntimeError)):
            # ValidationError details may contain response text; keep console bounded.
            print(
                "Check input/proposal schema, allowed ranges, API key/status and response status."
            )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
