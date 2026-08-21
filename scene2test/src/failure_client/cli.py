"""Command-line entry point for the Scene2Test Client control plane."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from failure_client.api import HttpSimulationGateway
from failure_client.config import ClientSettings
from failure_client.contracts import GatewayError
from failure_client.evaluation import FailureDefinition
from failure_client.experiments import (
    ExperimentOrchestrator,
    ExperimentProtocol,
    ReevaluationService,
)
from failure_client.methods import MethodRegistry
from failure_client.registry import RegistrySynchronizer
from failure_client.storage import ClientRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="failure-client",
        description="Client control plane for remote robot failure-discovery experiments.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health", help="check the remote Server health endpoint")
    subparsers.add_parser("registry-sync", help="synchronize capabilities and registry metadata")
    subparsers.add_parser("method-list", help="list built-in and installed method plugins")
    export = subparsers.add_parser(
        "export",
        help="export confirmed failure reproduction manifests for an experiment",
    )
    export.add_argument("experiment_id")
    reevaluate = subparsers.add_parser(
        "reevaluate",
        help="append evaluations for stored raw results using a new definition",
    )
    reevaluate.add_argument("experiment_id")
    reevaluate.add_argument("definition", type=Path)

    for name, help_text in (
        ("validate", "validate a protocol against the current Server"),
        ("run", "start a new immutable experiment"),
        ("resume", "resume an existing experiment without duplicate rollout submission"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("protocol", type=Path, help="experiment protocol YAML path")
        command.add_argument(
            "--poll-interval",
            type=float,
            default=1.0,
            help="seconds between remote job status polls (default: 1.0)",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "method-list":
            methods = MethodRegistry.with_builtins(load_external=True).list_plugin_ids()
            _print_json({"methods": methods})
            return 0
        settings = ClientSettings.from_env()
        settings.workspace_dir.mkdir(parents=True, exist_ok=True)
        repository = ClientRepository(settings.database_path)
        with HttpSimulationGateway(settings.gateway_config()) as gateway:
            if args.command == "health":
                _print_json(gateway.get_health())
                return 0
            if args.command == "registry-sync":
                result = RegistrySynchronizer(repository, gateway).sync()
                _print_json(result.model_dump(mode="json"))
                return 0

            if args.command == "export":
                orchestrator = ExperimentOrchestrator(
                    repository,
                    gateway,
                    workspace_dir=settings.workspace_dir,
                )
                result = orchestrator.export_experiment(args.experiment_id)
                _print_json(result.model_dump(mode="json"))
                return 0
            if args.command == "reevaluate":
                payload = yaml.safe_load(args.definition.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("failure definition must be a YAML object")
                definition = FailureDefinition.model_validate(payload)
                result = ReevaluationService(repository).run(
                    args.experiment_id,
                    definition,
                )
                _print_json(result.model_dump(mode="json"))
                return 0

            protocol = ExperimentProtocol.load_yaml(args.protocol)
            orchestrator = ExperimentOrchestrator(
                repository,
                gateway,
                workspace_dir=settings.workspace_dir,
                repository_dir=Path.cwd(),
                dependency_lock_path=Path.cwd() / "uv.lock",
                poll_interval_s=args.poll_interval,
            )
            if args.command == "validate":
                report = orchestrator.validate_protocol(protocol)
                _print_json(report)
                return 0
            summary = orchestrator.run(protocol, resume=args.command == "resume")
            _print_json(summary.model_dump(mode="json"))
            return 0
    except (GatewayError, ValidationError, ValueError, KeyError, OSError) as exc:
        _print_json(
            {
                "status": "error",
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
            stream=sys.stderr,
        )
        return 2


def _print_json(value: Any, *, stream: Any = sys.stdout) -> None:
    print(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        file=stream,
    )


if __name__ == "__main__":
    raise SystemExit(main())
