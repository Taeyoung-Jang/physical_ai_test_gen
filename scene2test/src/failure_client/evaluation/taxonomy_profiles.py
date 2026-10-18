"""One explicit search measurement contract for history, observations and metrics."""

from .failure_taxonomy import classify_record, profile_for_scene, rules_for_profile
from .research_records import EXPANDED_FAMILIES, FAMILIES


def metric_options(schema, mode="scene-default"):
    if mode == "scene-default":
        return {
            "family_rules": rules_for_profile(profile_for_scene(schema)),
            "family_inventory": FAMILIES,
        }
    if mode == "expanded-ten-v1":
        from .expanded_taxonomy import RULES

        return {"family_rules": dict(RULES), "family_inventory": EXPANDED_FAMILIES}
    raise ValueError("unknown search taxonomy profile")


def classify_for_search(record, schema, mode="scene-default"):
    metric_options(schema, mode)  # Validate even for excluded inputs.
    if mode == "expanded-ten-v1":
        from .expanded_taxonomy import classify_expanded

        return classify_expanded(record)
    return classify_record(record, profile=profile_for_scene(schema))
