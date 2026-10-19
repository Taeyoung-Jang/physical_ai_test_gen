"""Domain/measurement compatibility audit; no simulation, verdict or causal claims."""

from collections import defaultdict

from clear_path.contracts import parse_fixture
from clear_path.humans import human_scene
from clear_path.scene_space import axes_for_schema
from failure_client.evaluation.research_records import EXPANDED_FAMILIES
from failure_client.evaluation.taxonomy_profiles import metric_options
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics


def audit_discovery(schema, records=()):
    axes = axes_for_schema(schema)
    options = metric_options(schema, "expanded-ten-v1")
    rules = options["family_rules"]
    grouped = defaultdict(list)
    for record in records:
        grouped[record.condition_id or "excluded_without_condition"].append(record)
    observations = {
        condition: calculate_discovery_metrics(rows, **options)
        for condition, rows in grouped.items()
    }
    goal = {"target_xy_m": [7.0, 0.0], "radius_m": 0.25, "dwell_s": 1.0}
    human = None
    if "human_x_m" in axes:
        contract = human_scene(parse_fixture({"schema_version": schema}))
        radius = contract["robot_base_radius_m"] + contract["proxies"][0]["protected_radius_m"]
        low, high = axes["human_x_m"]
        x = goal["target_xy_m"][0]
        gap = max(low - x, x - high, 0) - goal["radius_m"] - radius
        human = {
            "human_x_bounds_m": list(axes["human_x_m"]),
            "exposure_center_distance_m": radius,
            "goal_disk_to_exposure_lower_gap_m": gap,
            "simultaneous_inside_goal_and_exposure": "PROVEN_DISJOINT" if gap > 0 else "UNKNOWN",
            "scope": "Static proxy X band and goal disk only, NOT whole episode reachability",
            "implication": (
                "Near-goal endings cannot expose this proxy. Human-family FAIL may still occur "
                "if the robot terminates near the proxy; earlier passage alone is not counted. "
                "Consider a separately versioned near-goal human domain, not weaker thresholds."
            ),
        }
    groups = {
        "collision": [a for a in axes if a.startswith("obstacle_") or a == "corridor_width_m"],
        "obstacle_interference": [
            a for a in axes if a.startswith("obstacle_") or a == "corridor_width_m"
        ],
        "goal_occupied": [
            a for a in axes if a in {"box_goal_x_m", "box_lateral_fraction", "corridor_width_m"}
        ],
        "human_safety_risk": [a for a in axes if a.startswith("human_")],
        "fall": [a for a in axes if a == "floor_friction" or a.endswith("height_m")],
        "locomotion_stall": [a for a in axes if a == "floor_friction" or a.startswith("obstacle_")],
        "manipulation_failure": [a for a in axes if a.startswith("box_")],
        "goal_completion_failure": [
            a for a in axes if a in {"box_goal_x_m", "box_lateral_fraction", "corridor_width_m"}
        ],
    }
    caveats = {
        "collision": "Box/floor contacts excluded; planning rejection is not collision",
        "obstacle_interference": "Needs recent repeated blockage, proximity AND terminal stall",
        "goal_occupied": (
            "Entire goal disk, not partial overlap/planner inflation, plus terminal stall"
        ),
        "human_safety_risk": "Last five seconds only; no whole-route or real safety certificate",
        "fall": "Conservative locomotion may avoid challenging contacts; no guarantee of falls",
        "locomotion_stall": (
            "Actual execution duration/motion, not inference or short rejected tools"
        ),
        "manipulation_failure": "Robot may bypass object; no request means mechanism untested",
        "goal_completion_failure": "Final inside-goal short dwell only, not every budget FAIL",
    }
    return {
        "schema_version": "discovery-readiness-v1",
        "scene_schema": schema,
        "goal": goal,
        "families": [
            {
                "family": f,
                "rule_status": "SUPPORTED" if f in rules else "UNSUPPORTED",
                "rule_version": rules.get(f),
                "relevant_axes": groups.get(f, []),
                "attainability": "NOT_PROVEN",
                "measurement_caveat": caveats.get(f, "Requires an independent evidence contract"),
            }
            for f in EXPANDED_FAMILIES
        ],
        "human_goal_compatibility": human,
        "observations_by_condition": observations,
        "supported_rule_count": len(rules),
        "target_family_count": 4,
        "claim": (
            "Rule support and controllable axes are not observed coverage or attainable failures"
        ),
        "cross_condition_pooling": False,
        "next_gates": [
            "Separate anchor and analysis references; replay saved response before paid dispatch",
            "Review family-specific behavior engagement, not changed axes alone",
            "Freeze domain/robot/goal/rules/search/budget before independent evaluation",
            "Confirm representative failures using separately charged regression attempts",
        ],
    }
