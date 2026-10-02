"""Offline capability audit for the current clear-path domains, NOT rollout coverage.

Separate implemented rules, controllable initial geometry and observed outcomes.
Conservative envelopes prove initial separation only. A movable box can subsequently
move; no_path cannot prove failure when manipulation or other actions are available.
This audit neither filters AFS candidates nor changes any robot/evaluation condition.
"""

import hashlib
import math
from pathlib import Path

from clear_path import fixture
from clear_path.contracts import CorridorFixture, GoalRegionFixture, ObstacleFixture, parse_fixture
from clear_path.scene_space import SCHEMAS, axes_for_schema
from robot_vlm.task_outcome import digest, task_contract

from .failure_taxonomy import PROFILE, RULES
from .research_records import FAMILIES

VERSION = "failure-domain-readiness-v2"


def _distance(point, rectangle):
    x0, x1, y0, y1 = rectangle
    return math.hypot(max(x0 - point[0], point[0] - x1, 0), max(y0 - point[1], point[1] - y1, 0))


def initial_envelopes(schema):
    """Conservative XY unions over ALL bounds, not a random sample proof.

    Current wall coordinates and box lateral placement are affine in width.
    Any rotated block half-extent is <= half of its maximum local diagonal.
    A full corridor-height Y envelope is conservative for all lateral fractions.
    Only the explicitly reviewed v1/v2/v3/v4 recipes are supported.
    """
    if schema not in SCHEMAS:
        raise ValueError("domain readiness requires a reviewed scene schema")
    config = parse_fixture({"schema_version": schema})
    axes = axes_for_schema(schema)
    widths = axes.get("corridor_width_m")
    variants = (
        [parse_fixture({"schema_version": schema, "corridor_width_m": w}) for w in widths]
        if widths
        else [config]
    )
    walls = [fixture.walls(c) for c in variants]
    rows = []
    for name in walls[0]:
        rects = [w[name] for w in walls]
        rows.append(
            {
                "object_id": name,
                "dynamic": False,
                "xy_envelope_m": [
                    min(r[0] for r in rects),
                    max(r[1] for r in rects),
                    min(r[2] for r in rects),
                    max(r[3] for r in rects),
                ],
                "derivation": "union of affine wall-coordinate extrema over the width domain",
            }
        )
    bx, by = fixture.box_start(config)
    hx, hy = fixture.BOX_SIZE[0] / 2, fixture.BOX_SIZE[1] / 2
    box_y = [-hy + by, hy + by]
    if widths:
        # The free lateral space is nonnegative throughout each supported domain.
        h = widths[1] / 2
        box_y = [-h + 0.05, h - 0.05]
    box_x = axes.get("box_goal_x_m", (bx, bx))
    rows.append(
        {
            "object_id": "clear_box",
            "dynamic": True,
            "xy_envelope_m": [box_x[0] - hx, box_x[1] + hx, *box_y],
            "derivation": "union over admitted box X, width and lateral fraction; fixed size",
        }
    )
    if isinstance(config, ObstacleFixture):
        for i in (1, 2):
            prefix = f"obstacle_{i}"
            half_diagonal = (
                math.hypot(axes[prefix + "_size_x_m"][1], axes[prefix + "_size_y_m"][1]) / 2
            )
            x0, x1 = axes[prefix + "_x_m"]
            h = widths[1] / 2
            rows.append(
                {
                    "object_id": prefix,
                    "dynamic": False,
                    "xy_envelope_m": [x0 - half_diagonal, x1 + half_diagonal, -h, h],
                    "derivation": "X band +/- maximum half-diagonal; full corridor Y envelope",
                }
            )
    return rows


def _initial_goal_check(schema, goal):
    rows = initial_envelopes(schema)
    radius = goal["radius_m"]
    for row in rows:
        row["goal_disk_separation_lower_bound_m"] = (
            _distance(goal["target_xy_m"], row["xy_envelope_m"]) - radius
        )
    separated = all(r["goal_disk_separation_lower_bound_m"] > 1e-9 for r in rows)
    witnesses = []
    config = parse_fixture({"schema_version": schema})
    if isinstance(config, GoalRegionFixture):
        for offset in (1.0, 0.5, 0.0):
            example = GoalRegionFixture(box_lateral_fraction=offset)
            witnesses.append(
                {
                    "scene_config": example.model_dump(),
                    "relation": fixture.initial_goal_relation(
                        example, target_xy=goal["target_xy_m"], radius_m=radius
                    ),
                }
            )
    constructed = any(w["relation"]["relation"] == "FULLY_COVERED" for w in witnesses)
    return {
        "status": "CONSTRUCTIVE_INITIAL_OCCUPANCY"
        if constructed
        else ("PROVEN_DISJOINT_AT_INITIALIZATION" if separated else "UNKNOWN"),
        "scope": "all admitted initial configurations; projected non-floor scene objects",
        "initial_occupancy_possible": True if constructed else False if separated else None,
        "constructive_examples": witnesses,
        "post_action_occupancy_possible": None,
        "post_action_status": "UNKNOWN_MOVABLE_OBJECT_CAN_MOVE",
        "envelopes": rows,
        "limits": [
            "Overlapping conservative envelopes are UNKNOWN, never a constructive occupancy proof",
            "No statement about robot feasibility, completed goals or subsequent box motion",
            "The floor supports the goal and is not a goal-blocking object",
        ],
    }


def _map_probes(schema):
    """CPU witnesses of static-map behavior, not simulated robot outcomes."""
    axes = axes_for_schema(schema)
    probes = []
    variants = [("default", {})]
    if "corridor_width_m" in axes:
        variants = [
            ("width_low", {"corridor_width_m": axes["corridor_width_m"][0]}),
            ("width_high", {"corridor_width_m": axes["corridor_width_m"][1]}),
        ]
    if "box_goal_x_m" in axes:
        variants = [
            ("goal_clear", {"box_lateral_fraction": 1.0}),
            ("goal_partial", {"box_lateral_fraction": 0.5}),
            ("goal_covered", {"box_lateral_fraction": 0.0}),
        ]
    for name, extra in variants:
        config = parse_fixture({"schema_version": schema, **extra})
        nav = fixture.navigation_map(config)
        graph = fixture.graph(config)
        probes.append(
            {
                "name": name,
                "scene_config": config.model_dump(),
                "scene_revision": fixture.identity(config),
                "scene_graph_sha256": digest(graph),
                "map_sha256": digest(nav),
                "static_map_reachable": nav["reachable"],
                "effective_radius_m": nav["effective_radius_m"],
                "goal_outcome": None,
                **(
                    {"initial_goal_relation": fixture.initial_goal_relation(config)}
                    if isinstance(config, GoalRegionFixture)
                    else {}
                ),
                "claim": "fixture map only; NOT the live follower/planner or a robot rollout",
            }
        )
    return probes


def _sources():
    src = Path(__file__).resolve().parents[2]
    paths = [
        "clear_path/contracts.py",
        "clear_path/scene_space.py",
        "clear_path/fixture.py",
        "clear_path/obstacles.py",
        "scene_graph.py",
        "robot_vlm/task_outcome.py",
        "failure_client/evaluation/failure_taxonomy.py",
        "failure_client/evaluation/research_records.py",
        "failure_client/evaluation/domain_readiness.py",
        "failure_client/evaluation/human_proximity.py",
    ]
    return {p: hashlib.sha256((src / p).read_bytes()).hexdigest() for p in paths}


def audit_domain(schema="clear-path-obstacles-v3"):
    if schema not in SCHEMAS:
        raise ValueError("domain readiness requires a reviewed scene schema")
    config = parse_fixture({"schema_version": schema})
    axes = axes_for_schema(schema)
    # Budgets have no bearing on this initial-geometry audit. Only read the goal.
    goal = task_contract(fixture.GOAL, 10, None)["goal"]
    initial = _initial_goal_check(schema, goal)
    geometry_axes = [k for k in axes if k not in {"box_mass_kg", "box_friction", "floor_friction"}]
    rows = {
        "collision": {
            "scene_control_status": "CONTACT_GEOMETRY_AVAILABLE",
            "relevant_axes": list(axes),
            "observations": ["robot/world contact intervals", "forces", "goal progress"],
            "gap": (
                "Contact is not automatically a goal failure or its cause; "
                "validate positive/negative traces"
            ),
        },
        "obstacle_interference": {
            "scene_control_status": "OBSTACLE_GEOMETRY_AVAILABLE",
            "relevant_axes": geometry_axes,
            "observations": ["plan/tool results", "terminal stagnation", "object proximity"],
            "gap": "Blocked static planning is not proof that the robot cannot achieve its goal",
        },
        "goal_occupied": {
            "scene_control_status": (
                "NO_INITIAL_OCCUPANCY_IN_DOMAIN"
                if initial["initial_occupancy_possible"] is False
                else "INITIAL_OCCUPANCY_CONTROLLABLE"
                if initial["initial_occupancy_possible"] is True
                else "UNKNOWN"
            ),
            "relevant_axes": ["box_goal_x_m", "box_lateral_fraction", "corridor_width_m"]
            if isinstance(config, GoalRegionFixture)
            else [],
            "observations": [
                "goal-region geometry",
                "audited object motion",
                "terminal stagnation",
            ],
            "gap": "Initial geometry is controllable; live success/failure evidence is still needed"
            if isinstance(config, GoalRegionFixture)
            else (
                "No direct initial goal-occupancy axis; later movable-box occupancy remains unknown"
            ),
        },
        "unreachable": {
            "scene_control_status": "NO_WHOLE_ROBOT_FEASIBILITY_CERTIFICATE",
            "relevant_axes": geometry_axes,
            "observations": ["static map/tool results (insufficient)"],
            "gap": (
                "Independent capability-aware constraints are required; "
                "no_path alone is insufficient"
            ),
        },
        "human_safety_risk": {
            "scene_control_status": "NO_HUMAN_PROXY_IN_SCENE",
            "development_status": "EXPERIMENTAL_MEASUREMENT_CONTRACT_ONLY",
            "relevant_axes": [],
            "observations": [],
            "gap": (
                "Offline human-proxy calculator exists; live scene and manifest-bound "
                "trace integration are absent. Not registered as a fourth family detector"
            ),
        },
        "perception_error": {
            "scene_control_status": "NO_CONTROLLED_PERCEPTION_CONTRAST",
            "relevant_axes": [],
            "observations": ["camera images", "ground-truth map/geometry"],
            "gap": (
                "Need robot perceptual assertions matched to sensor/GT evidence; "
                "GT assistance and observation changes must be declared"
            ),
        },
    }
    for name, row in rows.items():
        row.update(
            family=name,
            rule_status="IMPLEMENTED_OPERATIONAL" if name in RULES else "UNSUPPORTED",
            rule_version=RULES.get(name),
            observed_failure_count=None,
            observed_status="NOT_MEASURED",
            causal_status="NOT_ASSESSED",
        )
    count = len(set(RULES) & set(FAMILIES))
    report = {
        "schema_version": VERSION,
        "scene_schema": schema,
        "axes": axes,
        "axis_count": len(axes),
        "goal": goal,
        "taxonomy_profile": PROFILE,
        "families": [rows[f] for f in FAMILIES],
        "initial_goal_occupancy": initial,
        "static_map_probes": _map_probes(schema),
        "target_readiness": {
            "target_family_count": 4,
            "total_family_count": len(FAMILIES),
            "implemented_rule_count": count,
            "minimum_additional_rules_needed": max(0, 4 - count),
            "status": "INSUFFICIENT_RULE_SUPPORT"
            if count < 4
            else "REQUIRES_VALIDATED_SCENARIOS_AND_ROLLOUTS",
            "observed_failure_diversity_coverage": None,
            "claim": "Rule inventory is neither validated family coverage nor a discovery result",
        },
        "priorities": [
            {
                "id": "goal_region_scene_control",
                "kind": "IMPLEMENTED_REQUIRES_LIVE_VALIDATION"
                if isinstance(config, GoalRegionFixture)
                else "AVAILABLE_IN_SEPARATE_V4_DOMAIN",
                "reason": (
                    "Connect existing goal-occupancy measurement to explicit, versioned "
                    "object placement and clear/partial/covered controls"
                ),
            },
            {
                "id": "fourth_family_contract",
                "kind": "CONTRACT_AND_REFERENCE_CALCULATOR_ONLY",
                "reason": (
                    "Human proximity contract is experimental; implement and validate "
                    "scene/trace binding before registration. It must not relabel goal PASS"
                ),
            },
            {
                "id": "search_quality_validation",
                "kind": "EXISTING_COMPONENTS_TO_VALIDATE",
                "reason": (
                    "Reuse behavior feedback, novelty and success-side contrasts "
                    "under the fixed robot condition"
                ),
            },
        ],
        "execution": {"robot_rollouts": 0, "api_calls": 0, "goal_labels_assigned": 0},
        "source_hashes": _sources(),
        "limits": [
            "Static source-bound capability audit; not six-family measurement of a campaign",
            "No robot actions, physical integration, GPU inference or paid API calls",
            "No labels, budgets, archived outcomes or frozen campaigns are modified",
            "Current goal-agent v1/v2/v3/v4 only; separate maze/terrain backends are not included",
            "Initial geometry cannot predict all post-action states of movable objects",
        ],
        "scene_kind": "corridor" if isinstance(config, CorridorFixture) else "box_and_bay",
    }
    report["audit_sha256"] = digest(report)
    return report
