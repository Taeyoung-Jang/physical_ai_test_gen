"""Anchored development contrasts, deliberately separate from AFS/Random trials.

Reuse measured P1 brackets, hypothesis selection and the durable regression executor.
Only scenes change. Imported history is disclosed and never a benchmark arm.
"""

from copy import deepcopy
from html import escape
from pathlib import Path

from clear_path.scene_space import axes_for_parameters
from failure_client.archive.regression_cases import build_failure_memory
from failure_client.evaluation.behavior_measures import verify_episode_files
from failure_client.evaluation.goal_run_reader import read_goal_run, read_json
from failure_client.evaluation.research_records import EpisodeRecord, RunInput
from failure_client.methods.behavior_feedback import (
    boundary_candidate,
    choose_probe,
    feedback_context,
    parameters,
    repeat_candidate,
)
from llm_afs.behavior_request import request
from robot_vlm.task_outcome import digest

MODE = "anchored_scene_contrast_v1"


def evidence(paths):
    if not 1 <= len(paths) <= 32:
        raise ValueError("select 1..32 verified archives in observation order")
    records = [read_goal_run(RunInput(path=str(Path(p).resolve()))) for p in paths]
    if any(r.status != "VALID" for r in records):
        raise ValueError("only VALID goal outcomes may guide contrasts; inspect exclusions first")
    memory = build_failure_memory(records)
    cases = memory["cases"]
    if (
        not cases
        or any(c["parameters"] is None or c["geometry_id"] is None for c in cases)
        or len({c["condition_id"] for c in cases}) != 1
        or len({c["geometry_id"] for c in cases}) != 1
        or len({c["parameters"]["schema_version"] for c in cases}) != 1
    ):
        raise ValueError("contrasts require one verified robot/task/budget/geometry condition")
    return memory


def contrast_plan(paths, *, axis, values, repeats=1, anchor=None, selection=None):
    """An explicit control plus up to four one-axis probes. No API or robot execution."""
    from .behavior_regression import replay_plan

    memory = evidence(paths)
    latest = list(memory["episodes"])[-1]
    base = next(
        (
            c
            for c in memory["cases"]
            if (c["case_id"] == anchor if anchor else latest in c["episodes"])
        ),
        None,
    )
    if base is None:
        raise ValueError("anchor must identify a verified supplied case")
    axes = axes_for_parameters(base["parameters"])
    if axis not in axes or not 0 <= len(values) <= 4:
        raise ValueError("one supported axis and at most four probe values required")
    if len(set(values)) != len(values) or base["parameters"][axis] in values:
        raise ValueError("probe values must be distinct from each other and the control")
    baselines = [memory["episodes"][e]["record"]["source"]["path"] for e in base["episodes"]]
    plan = replay_plan(baselines, repeats=repeats)
    reference = plan["cases"][0]
    reference.update(
        contrast_role="control_repeat",
        changed_axis=None,
        expected_condition_id=base["condition_id"],
    )
    for value in values:
        case = deepcopy(reference)
        case["scene"][axis] = value
        case.update(
            case_id=digest([MODE, base["case_id"], axis, value]),
            contrast_role="single_axis_probe",
            changed_axis=axis,
        )
        plan["cases"].append(case)
    plan.update(
        mode=MODE,
        reference_scene=base["parameters"],
        anchor_case_id=base["case_id"],
        axis=axis,
        selection=selection or {"origin": "operator_selected_contrast", "axis": axis},
        history=[e["record"] for e in memory["episodes"].values()],
        history_duplicates=memory["duplicates"],
        max_attempts=len(plan["cases"]) * repeats,
        robot_api_call_upper_bound=len(plan["cases"])
        * repeats
        * reference["target_config"]["robot"]["max_calls"],
        limits=[
            "Operator-seeded development search with external history; NOT an AFS/Random benchmark",
            "Only one scene parameter changes; derived coordinates can change with corridor width",
            "Robot/model/goal/budget/completion stay fixed; remote inference is not deterministic",
            "Opposite outcomes are observed brackets, not causal or monotonic boundary proofs",
            "Control/repeat/excluded attempts consume the fixed budget; no replacement or retry",
            "Inherited evidence costs and new execution costs are separate; no Gain claim",
            "MP4 only; no GIF, implicit simulation cap or client output token cap",
        ],
    )
    validate_plan(plan)
    return plan


def validate_plan(plan):
    from .research_protocol import CampaignConfig

    if plan.get("mode") != MODE:
        raise ValueError("not a contrast plan")
    reference = plan["reference_scene"]
    cases = plan["cases"]
    history = [EpisodeRecord.model_validate(r) for r in plan["history"]]
    if not history or len({r.condition_id for r in history}) != 1:
        raise ValueError("contrast history condition mismatch")
    if not 1 <= len(cases) <= 5 or not 1 <= plan["attempts_per_case"] <= 10:
        raise ValueError("contrast attempt budget invalid")
    if len({c["case_id"] for c in cases}) != len(cases):
        raise ValueError("duplicate contrast case")
    for i, case in enumerate(cases):
        cfg = CampaignConfig.model_validate(case["target_config"])
        params = {k: case["scene"][k] for k in axes_for_parameters(reference)}
        if cfg.scene(params).model_dump() != case["scene"]:
            raise ValueError("unsupported scene settings would change at execution")
        changed = {k for k in reference if case["scene"].get(k) != reference[k]}
        if changed != (set() if i == 0 else {plan["axis"]}):
            raise ValueError("contrast must preserve every other scene parameter")
        if (
            case["expected_condition_id"] != history[0].condition_id
            or any(r["condition_id"] != history[0].condition_id for r in case["baselines"])
            or case["target_config"] != cases[0]["target_config"]
        ):
            raise ValueError("contrast robot condition mismatch")
        for record, p in zip(case["baselines"], case["baseline_protocols"], strict=True):
            if read_json(Path(record["source"]["path"]) / "protocol.json") != p:
                raise ValueError("saved baseline protocol mismatch")
            from robot_vlm.navigation_completion import profile_from_protocol

            if (
                p["scene_config"] != reference
                or p["task_contract"] != case["task_contract"]
                or cfg.robot.model != p["model"]
                or cfg.robot.max_calls != p["max_calls"]
                or cfg.robot.max_seconds != p["max_simulation_s"]
                or cfg.robot.response_timeout != p["http_read_timeout_s"]
                or cfg.robot.enable_push != p["push_enabled"]
                or cfg.robot.navigation_completion != profile_from_protocol(p)
            ):
                raise ValueError("contrast may not override baseline robot/task settings")
    if plan["max_attempts"] != len(cases) * plan["attempts_per_case"] or plan[
        "robot_api_call_upper_bound"
    ] != sum(c["target_config"]["robot"]["max_calls"] * plan["attempts_per_case"] for c in cases):
        raise ValueError("contrast budget mismatch")


def verify_condition(plan, env):
    """Preflight the archived source/resource/runtime hashes, before spending money.

    Goal protocol source keys are aliases. The frozen environment maps actual source
    paths; require every archived digest to exist, without importing MuJoCo/GPU code.
    The full returned condition_id is additionally checked after every rollout.
    """
    validate_plan(plan)
    for row in plan["history"]:
        verify_episode_files(EpisodeRecord.model_validate(row))
    for case in plan["cases"]:
        for p in case["baseline_protocols"]:
            if (
                not p["source_hashes"]
                or not set(p["source_hashes"].values()) <= set(env["source_hashes"].values())
                or any(env["robot_resources"].get(k) != v for k, v in p["robot_resources"].items())
                or any(
                    env["runtime_versions"].get(k) != v
                    for k, v in p.get("runtime_versions", {}).items()
                )
            ):
                raise ValueError("archived robot code/resources/runtime changed; contrast refused")


def next_selection(memory, *, raw=None):
    """Mixed repeats first, then measured midpoint, otherwise the existing LLM selector."""
    candidate = repeat_candidate(memory, mixed_only=True) or boundary_candidate(memory)
    if candidate is not None:
        return candidate, None
    schema = memory["cases"][-1]["parameters"]["schema_version"]
    ctx = feedback_context(memory, history_limit=8, remaining=1, scene_schema=schema)
    ctx["development_search"] = {
        "mode": MODE,
        "external_history": True,
        "benchmark_comparison": False,
        "next_suite": "one anchor repeat plus one selected endpoint; no robot launched here",
    }
    # Existing hypothesis ranking, with a prompt describing this workflow exactly.
    if raw is not None:
        candidate = choose_probe(raw, ctx, memory)
    return candidate, ctx


def selected_plan(paths, candidate):
    memory = evidence(paths)
    target = candidate["parameters"]
    matches = [
        c for c in memory["cases"] if sum(parameters(c)[k] != target[k] for k in target) <= 1
    ]
    if not matches:
        raise ValueError("selected candidate has no single-axis anchor")
    anchor = candidate.get("selection_audit", {}).get("anchor_case_id")
    if candidate["stage"] == "repeat":
        anchor = candidate["evidence"]["case_id"]
    elif candidate["stage"] == "boundary":
        anchor = candidate["evidence"]["low"]["case_ids"][0]
    if not anchor:
        raise ValueError("selected candidate lacks its audited anchor")
    base = next((c for c in matches if c["case_id"] == anchor), None)
    if base is None:
        raise ValueError("selected candidate differs from its audited anchor on multiple axes")
    changed = [k for k in target if parameters(base)[k] != target[k]]
    axis = changed[0] if changed else next(iter(axes_for_parameters(base["parameters"])))
    return contrast_plan(
        paths,
        axis=axis,
        values=[target[axis]] if changed else [],
        anchor=base["case_id"],
        selection=candidate,
    )


def next_request(paths, *, model="gpt-6-luna"):
    memory = evidence(paths)
    candidate, ctx = next_selection(memory)
    return (
        memory,
        candidate,
        ctx,
        (request(ctx, model, selection_policy="anchored_contrast_endpoint") if ctx else None),
    )


def write_preview(root, plan):
    """Derived static preview only; never feed a reference route to the robot."""
    from clear_path import fixture
    from clear_path.contracts import parse_fixture
    from clear_path.report import plot_map

    from .local_goal_adapter import atomic_json

    root = Path(root) / "preview"
    root.mkdir(exist_ok=False)
    sections = []
    for i, case in enumerate(plan["cases"]):
        scene = parse_fixture(case["scene"])
        nav = fixture.navigation_map(scene)
        atomic_json(root / f"scene_{i:03}.json", case["scene"])
        atomic_json(root / f"graph_{i:03}.json", fixture.graph(scene))
        plot_map(nav, root / f"scene_{i:03}.png", scene)
        role = case.get("probe_purpose", case["contrast_role"])
        label = f"{role}: {plan['axis']} = {case['scene'][plan['axis']]}"
        sections.append(
            f'<h2>{escape(label)}</h2><img src="scene_{i:03}.png" '
            'style="max-width:100%" alt="Static scene preview">'
        )
    (root / "index.html").write_text(
        '<!doctype html><html lang="ko"><meta charset="utf-8"><title>대조 장면 미리보기</title>'
        "<h1>단일 축 장면 대조 계획</h1><p>로봇 실행 전 정적 지도입니다. "
        "선은 실제 로봇 궤적이나 로봇에게 제공되는 정답 경로가 아닙니다. "
        "경로 유무로 성공·실패를 판정하거나 후보를 제외하지 않습니다.</p>"
        + "".join(sections)
        + "</html>",
        encoding="utf-8",
    )
    return root / "index.html"
