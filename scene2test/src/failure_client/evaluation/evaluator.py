"""Deterministic evaluation of server evidence against Client-owned rules."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from failure_client.contracts import RemoteJobState, RolloutResult, canonical_sha256

from .models import (
    EvaluationOutcome,
    EventMeasurementPredicate,
    FailureDefinition,
    ResearchEvaluation,
    ValuePredicate,
)

_MISSING = object()


class FailureEvaluator:
    evaluator_id = "failure-client.rules"
    evaluator_version = "1.0.0"

    def evaluate(
        self,
        *,
        experiment_id: str,
        attempt_id: str,
        candidate_id: str,
        repeat_index: int,
        definition: FailureDefinition,
        result: RolloutResult,
    ) -> ResearchEvaluation:
        definition_sha = canonical_sha256(definition)
        result_sha = canonical_sha256(result)
        evaluation_id = _evaluation_id(
            attempt_id,
            self.evaluator_id,
            self.evaluator_version,
            definition_sha,
            result_sha,
        )

        if not result.execution.valid or result.execution.status != RemoteJobState.SUCCEEDED:
            return ResearchEvaluation(
                evaluation_id=evaluation_id,
                experiment_id=experiment_id,
                attempt_id=attempt_id,
                candidate_id=candidate_id,
                repeat_index=repeat_index,
                evaluator_id=self.evaluator_id,
                evaluator_version=self.evaluator_version,
                definition_id=definition.definition_id,
                definition_version=definition.definition_version,
                definition_sha256=definition_sha,
                result_sha256=result_sha,
                outcome=EvaluationOutcome.INDETERMINATE,
                failure=None,
                diagnostic=result.execution.termination_reason or "invalid execution",
                objectives=_numeric_objectives(result),
                created_at=datetime.now(UTC),
            )

        predicate_matches = {
            rule.rule_id: _matches_predicate(rule, result) for rule in definition.failure_predicates
        }
        event_matches = {
            rule.rule_id: sum(
                event.event_type == rule.event_type
                and event.timestamp_s >= rule.after_timestamp_s
                and all(
                    _matches_measurement(predicate, event.measurements)
                    for predicate in rule.measurements
                )
                for event in result.standard_events
            )
            >= rule.minimum_count
            for rule in definition.failure_events
        }
        all_failure_matches = predicate_matches | event_matches
        matched_failure_rules = [
            rule_id for rule_id, matched in all_failure_matches.items() if matched
        ]
        failure_rule_triggered = _aggregate(
            list(all_failure_matches.values()),
            definition.failure_aggregation,
        )

        success_matches = {
            rule.rule_id: _matches_predicate(rule, result) for rule in definition.success_predicates
        }
        unmet_success_rules = [
            rule_id for rule_id, matched in success_matches.items() if not matched
        ]
        success_rule_satisfied = _aggregate(
            list(success_matches.values()),
            definition.success_aggregation,
            empty=True,
        )
        failed = failure_rule_triggered or not success_rule_satisfied

        return ResearchEvaluation(
            evaluation_id=evaluation_id,
            experiment_id=experiment_id,
            attempt_id=attempt_id,
            candidate_id=candidate_id,
            repeat_index=repeat_index,
            evaluator_id=self.evaluator_id,
            evaluator_version=self.evaluator_version,
            definition_id=definition.definition_id,
            definition_version=definition.definition_version,
            definition_sha256=definition_sha,
            result_sha256=result_sha,
            outcome=EvaluationOutcome.FAILURE if failed else EvaluationOutcome.SUCCESS,
            failure=failed,
            matched_failure_rules=matched_failure_rules,
            unmet_success_rules=unmet_success_rules,
            objectives=_numeric_objectives(result),
            created_at=datetime.now(UTC),
        )


def _matches_predicate(predicate: ValuePredicate, result: RolloutResult) -> bool:
    source = getattr(result, predicate.source)
    value = _resolve_path(source, predicate.path)
    return _compare(value, predicate.operator, predicate.expected)


def _matches_measurement(
    predicate: EventMeasurementPredicate,
    measurements: dict[str, Any],
) -> bool:
    return _compare(
        _resolve_path(measurements, predicate.path),
        predicate.operator,
        predicate.expected,
    )


def _compare(value: Any, operator: str, expected: Any) -> bool:
    if operator == "exists":
        return value is not _MISSING
    if value is _MISSING:
        return False
    if operator == "truthy":
        return bool(value)
    if operator == "falsy":
        return not bool(value)
    try:
        if operator == "eq":
            return value == expected
        if operator == "ne":
            return value != expected
        if operator == "lt":
            return value < expected
        if operator == "lte":
            return value <= expected
        if operator == "gt":
            return value > expected
        if operator == "gte":
            return value >= expected
    except TypeError:
        return False
    raise AssertionError(f"unsupported operator: {operator}")


def _resolve_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return _MISSING
    return current


def _aggregate(values: list[bool], mode: str, *, empty: bool = False) -> bool:
    if not values:
        return empty
    return any(values) if mode == "any" else all(values)


def _numeric_objectives(result: RolloutResult) -> dict[str, float]:
    return {
        key: float(value)
        for key, value in result.summary_metrics.items()
        if isinstance(value, int | float) and not isinstance(value, bool)
    }


def _evaluation_id(*parts: str) -> str:
    payload = "\0".join(parts).encode("utf-8")
    return f"evaluation_{hashlib.sha256(payload).hexdigest()[:32]}"
