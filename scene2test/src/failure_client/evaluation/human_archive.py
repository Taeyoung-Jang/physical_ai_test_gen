"""Bind static human proximity to verified v5 scene, geometry and sampled base trace."""

from clear_path.contracts import CrossingHumanFixture, HumanFixture
from clear_path.fixture import graph
from clear_path.humans import human_scene
from robot_vlm.scene_config import validate_scene

from .behavior_measures import _box_address, verify_episode_files
from .goal_run_reader import _rows, read_json
from .human_proximity import measure_human_proximity


def measure_archive_humans(record):
    """Research association only; never changes goal outcome or selects a primary family."""
    unknown = {
        "measurement_status": "UNKNOWN",
        "diagnostic_status": "UNKNOWN",
        "task_outcome": record.task_outcome,
        "evidence_binding": "UNVERIFIED",
        "eligible_for_family_coverage": False,
        "evidence": [],
    }
    if record.status != "VALID":
        return {**unknown, "reason": "excluded_episode"}
    try:
        root = verify_episode_files(record)
        protocol = read_json(root / "protocol.json")
        config = validate_scene(protocol["scene_config"])
        if isinstance(config, CrossingHumanFixture):
            return {
                **unknown,
                "measurement_status": "UNSUPPORTED",
                "reason": "dynamic_human_requires_separate_trajectory_detector",
            }
        if not isinstance(config, HumanFixture):
            return {
                **unknown,
                "measurement_status": "UNSUPPORTED",
                "reason": "no_human_scene_contract",
            }
        required = {"human_proxies.json", "scene_graph.json", "robot_audit.json"}
        if not required <= record.artifact_hashes.keys():
            return {**unknown, "reason": "missing_manifest_bound_human_evidence"}
        from failure_client.archive.regression_cases import _scene_parameters

        if _scene_parameters(root, protocol)[0] is None:
            raise ValueError("scene_geometry_not_verified")
        metadata = human_scene(config)
        if read_json(root / "human_proxies.json") != metadata:
            raise ValueError("human_metadata_differs_from_scene")
        if read_json(root / "scene_graph.json") != graph(config):
            raise ValueError("human_scene_graph_mismatch")
        audit = read_json(root / "robot_audit.json")
        if (
            audit.get("robot_joint_identity_preserved") is not True
            or audit.get("gait_observation_equal") is not True
        ):
            raise ValueError("robot_base_state_not_audited")
        states = list(_rows(root / "states.jsonl"))
        address = _box_address(root, record)
        if address is None or any(len(s["qpos"]) != address[1] for s in states):
            raise ValueError("robot_state_layout_mismatch")
        end = states[-1]["time_s"]
        start = end - metadata["terminal_window_s"]
        if start < 0 or states[0]["time_s"] > start or not 0 <= record.simulation_s - end <= 0.25:
            return {**unknown, "reason": "terminal_window_incomplete"}
        samples = []
        for a, b in zip(states, states[1:]):
            if a["time_s"] < start < b["time_s"]:
                if b["time_s"] - a["time_s"] > metadata["max_sample_gap_s"] + 1e-9:
                    return {**unknown, "reason": "gap_at_window_boundary"}
                fraction = (start - a["time_s"]) / (b["time_s"] - a["time_s"])
                samples.append(
                    {
                        "time_s": start,
                        "base_xy_m": [
                            x + fraction * (y - x) for x, y in zip(a["qpos"][:2], b["qpos"][:2])
                        ],
                    }
                )
                break
        samples.extend(
            {"time_s": s["time_s"], "base_xy_m": s["qpos"][:2]}
            for s in states
            if s["time_s"] >= start
        )
        contract = {
            k: metadata[k]
            for k in (
                "frame",
                "motion_model",
                "robot_base_radius_m",
                "max_sample_gap_s",
                "min_continuous_exposure_s",
            )
        }
        contract.update(
            start_s=start,
            end_s=end,
            proxies=[
                {k: p[k] for k in ("id", "semantic_role", "center_xy_m", "protected_radius_m")}
                for p in metadata["proxies"]
            ],
        )
        result = measure_human_proximity(contract, samples, task_outcome=record.task_outcome)
        result.update(
            family_detector_status="REGISTERED_OPERATIONAL",
            evidence_binding="VERIFIED_ARCHIVE_SCENE_AND_TRACE",
            evidence=[
                {"artifact": name, "sha256": record.artifact_hashes[name]}
                for name in sorted(
                    required | {"scene.xml", "protocol.json", "states.jsonl", "result.json"}
                )
            ],
            window=(
                "last five sampled simulation seconds; "
                "final sample at most 0.25s before termination"
            ),
        )
        result["limits"] = [
            "Static declared human proxies and piecewise-linear 2D base trace only",
            "Includes inference waits; not a whole-body or real-world safety certificate",
            "Exposure plus goal FAIL is temporal association, not proven failure causation",
        ]
        return result
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OSError):
        return {**unknown, "reason": "human_scene_or_trace_not_verified"}
