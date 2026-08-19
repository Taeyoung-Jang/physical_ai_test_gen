"""Export confirmed failures without credentials or expiring download URLs."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from failure_client.contracts import ContractModel, canonical_sha256
from failure_client.storage import ClientRepository


class FailureExportResult(ContractModel):
    experiment_id: str
    definition_sha256: str
    failure_case_count: int = Field(ge=0)
    manifest_path: Path
    manifest_sha256: str


class FailureCaseExporter:
    def __init__(self, repository: ClientRepository) -> None:
        self.repository = repository

    def export(
        self,
        *,
        experiment_id: str,
        definition_sha256: str,
        output_dir: Path,
    ) -> FailureExportResult:
        experiment = self.repository.get_experiment(experiment_id)
        cases = self.repository.list_failure_cases(
            experiment_id,
            definition_sha256=definition_sha256,
            confirmed_only=True,
        )
        exported_cases = []
        for case in cases:
            candidate = next(
                item
                for item in self.repository.list_candidates(experiment_id)
                if item.candidate_id == case.candidate_id
            )
            attempts = self.repository.list_rollout_attempts(
                experiment_id,
                case.candidate_id,
            )
            evaluations = self.repository.list_evaluations(
                experiment_id=experiment_id,
                candidate_id=case.candidate_id,
                definition_sha256=definition_sha256,
            )
            exported_attempts = []
            for attempt in attempts:
                result = attempt.result.model_dump(
                    mode="json",
                    by_alias=True,
                    exclude_none=True,
                ) if attempt.result is not None else None
                if result is not None:
                    for artifact in result.get("artifacts", []):
                        artifact.pop("download_url", None)
                exported_attempts.append(
                    {
                        "attempt_id": attempt.attempt_id,
                        "repeat_index": attempt.repeat_index,
                        "request_sha256": attempt.request_sha256,
                        "request": attempt.request.model_dump(
                            mode="json",
                            by_alias=True,
                            exclude_none=True,
                        ),
                        "job_id": attempt.job_id,
                        "state": attempt.state,
                        "result": result,
                        "artifacts": self.repository.list_artifacts(attempt.attempt_id),
                    }
                )
            exported_cases.append(
                {
                    "archive": case.model_dump(mode="json", exclude_none=True),
                    "candidate": candidate.candidate.model_dump(
                        mode="json",
                        by_alias=True,
                        exclude_none=True,
                    ),
                    "attempts": exported_attempts,
                    "evaluations": [
                        item.model_dump(mode="json", by_alias=True, exclude_none=True)
                        for item in evaluations
                    ],
                }
            )

        manifest: dict[str, Any] = {
            "schema_version": "1.0",
            "exported_at": datetime.now(UTC).isoformat(),
            "experiment_id": experiment_id,
            "parent_experiment_id": experiment["parent_experiment_id"],
            "definition_sha256": definition_sha256,
            "protocol": experiment["protocol"],
            "protocol_lock": experiment["protocol_lock"],
            "failure_cases": exported_cases,
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        suffix = definition_sha256.removeprefix("sha256:")[:16]
        path = output_dir / f"confirmed-failures-{suffix}.json"
        _atomic_json_write(path, manifest)
        return FailureExportResult(
            experiment_id=experiment_id,
            definition_sha256=definition_sha256,
            failure_case_count=len(exported_cases),
            manifest_path=path,
            manifest_sha256=canonical_sha256(manifest),
        )


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            dir=path.parent,
            prefix=".export-",
            encoding="utf-8",
            delete=False,
        ) as output:
            temp_path = Path(output.name)
            json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
