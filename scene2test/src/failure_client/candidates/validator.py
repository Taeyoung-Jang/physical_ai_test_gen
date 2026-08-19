"""Local schema/capability/dependency validation before remote submission."""

from __future__ import annotations

from failure_client.contracts import CapabilitySnapshot

from .models import BuiltCandidate, CandidateIssue, CandidateValidationResult


class CandidateValidator:
    def validate(
        self,
        candidate: BuiltCandidate,
        capabilities: CapabilitySnapshot,
    ) -> CandidateValidationResult:
        issues: list[CandidateIssue] = []
        limits = capabilities.limits
        if (
            limits.maximum_interventions is not None
            and len(candidate.interventions) > limits.maximum_interventions
        ):
            issues.append(
                CandidateIssue(
                    severity="ERROR",
                    code="MAXIMUM_INTERVENTIONS_EXCEEDED",
                    message=(
                        f"candidate has {len(candidate.interventions)} interventions; "
                        f"limit={limits.maximum_interventions}"
                    ),
                )
            )

        operation_ids = [item.operation_id for item in candidate.interventions]
        duplicates = sorted({item for item in operation_ids if operation_ids.count(item) > 1})
        for operation_id in duplicates:
            issues.append(
                CandidateIssue(
                    severity="ERROR",
                    code="DUPLICATE_OPERATION_ID",
                    message=f"duplicate operation id: {operation_id}",
                    operation_id=operation_id,
                )
            )

        available = {
            capability.operation_id: capability
            for capability in capabilities.intervention_operations
        }
        known_ids = set(operation_ids)
        dependency_graph: dict[str, list[str]] = {}
        for operation in candidate.interventions:
            capability_id = operation.kind.rsplit(".", 1)[-1]
            capability = available.get(capability_id)
            if capability is None:
                issues.append(
                    CandidateIssue(
                        severity="ERROR",
                        code="INTERVENTION_CAPABILITY_MISSING",
                        message=f"Server does not support {capability_id}",
                        operation_id=operation.operation_id,
                    )
                )
            elif (
                capability.version.split(".", 1)[0]
                != operation.operation_version.split(".", 1)[0]
            ):
                issues.append(
                    CandidateIssue(
                        severity="ERROR",
                        code="INTERVENTION_VERSION_MISMATCH",
                        message=(
                            f"operation requires {operation.operation_version}; "
                            f"available={capability.version}"
                        ),
                        operation_id=operation.operation_id,
                    )
                )
            missing = sorted(set(operation.depends_on) - known_ids)
            if missing:
                issues.append(
                    CandidateIssue(
                        severity="ERROR",
                        code="UNKNOWN_OPERATION_DEPENDENCY",
                        message=f"unknown dependencies: {missing}",
                        operation_id=operation.operation_id,
                    )
                )
            dependency_graph[operation.operation_id] = operation.depends_on

        if _has_cycle(dependency_graph):
            issues.append(
                CandidateIssue(
                    severity="ERROR",
                    code="CYCLIC_OPERATION_DEPENDENCY",
                    message="intervention dependency graph contains a cycle",
                )
            )
        return CandidateValidationResult(
            valid=not any(issue.severity == "ERROR" for issue in issues),
            issues=issues,
        )


def _has_cycle(graph: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dependency in graph.get(node, []):
            if dependency in graph and visit(dependency):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)
