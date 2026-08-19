"""Translate research intents into canonical Server InterventionSpec objects."""

from __future__ import annotations

from failure_client.contracts import InterventionSpec, canonical_sha256

from .models import BuiltCandidate, CandidateProposal

_OPERATION_KIND = {
    "add_primitive": "scene.add_primitive",
    "add_mesh": "scene.add_mesh",
    "move_object": "scene.move_object",
    "narrow_passage": "scene.narrow_passage",
    "set_robot_spawn": "robot_initial_state.set_spawn",
    "set_target_pose": "task.set_target_pose",
    "set_friction": "dynamics.set_friction",
    "camera_occlusion": "sensor.camera_occlusion",
}


class InterventionBuilder:
    def build(self, proposal: CandidateProposal) -> BuiltCandidate:
        intent = proposal.intervention_intent
        raw_operations = intent.get("operations")
        if raw_operations is None:
            raw_operations = [intent]
        if not isinstance(raw_operations, list) or not raw_operations:
            raise ValueError("intervention intent must contain at least one operation")

        interventions: list[InterventionSpec] = []
        for index, raw in enumerate(raw_operations):
            if not isinstance(raw, dict):
                raise ValueError("each intervention operation must be an object")
            operation = str(raw.get("operation") or raw.get("kind") or "").strip()
            if not operation:
                raise ValueError("intervention operation or kind is required")
            kind = _OPERATION_KIND.get(operation, operation)
            interventions.append(
                InterventionSpec(
                    operation_id=str(raw.get("operation_id") or f"op_{index:03d}"),
                    kind=kind,
                    operation_version=str(raw.get("operation_version") or "1.0"),
                    coordinate_frame=raw.get("coordinate_frame", "scene"),
                    parameters=dict(raw.get("parameters") or {}),
                    depends_on=list(raw.get("depends_on") or []),
                )
            )

        digest = canonical_sha256(
            {"interventions": [item.model_dump(mode="json") for item in interventions]}
        )
        return BuiltCandidate(
            proposal=proposal,
            interventions=interventions,
            canonical_sha256=digest,
        )

