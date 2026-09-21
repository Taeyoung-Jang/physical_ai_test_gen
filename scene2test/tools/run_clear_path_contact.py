"""P2 bounded real-physics unit probe, NOT complete clear-path task execution."""

import argparse
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kind", choices=["push_contact"], default="push_contact")
    p.add_argument("--initial-y", type=float, default=0.0)
    p.add_argument("--duration", type=float)
    p.add_argument(
        "--groot-root", type=Path, default=Path("/workspace/g1_failure/src/GR00T-WholeBodyControl")
    )
    p.add_argument(
        "--output-root", type=Path, default=Path("/workspace/g1_failure/runtime/clear_path_probes")
    )
    args = p.parse_args()
    duration = args.duration if args.duration is not None else 18
    if not 16 <= duration <= 20 or not -0.03 <= args.initial_y <= 0.03:
        p.error("duration 16..20 seconds, initial-y within +/-0.03 m required")
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ["SIM_SERVER_ONNX_PROVIDER"] = "cuda"
    import mujoco

    from clear_path import audit, contact_control, contact_probe, fixture, push_probe
    from clear_path.contracts import Fixture
    from simulation_server import groot_locomotion

    root = args.output_root.resolve() / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    root.mkdir(parents=True, exist_ok=False)
    print(f"CLEAR_PATH_PROBE={root}", flush=True)
    source = args.groot_root / "decoupled_wbc/sim2mujoco/resources/robots/g1/g1_gear_wbc.xml"
    try:
        xml = fixture.world_xml(Fixture(), source)
        with (root / "scene.xml").open("x") as f:
            f.write(xml)
        model = mujoco.MjModel.from_xml_string(xml)
        inspected = audit.inspect(source, model)
        write(root / "robot_audit.json", inspected)
        protocol = {
            "schema_version": "clear-path-probe-protocol-v1",
            "kind": args.kind,
            "maximum_duration_s": duration,
            "physics_dt": model.opt.timestep,
            "fixture_revision": fixture.identity(Fixture()),
            "mujoco_version": mujoco.__version__,
            "initial_robot_y": args.initial_y,
            "controller_condition": "contact_feedback_retract_v1",
            "initial_robot_x": 3.2 if args.kind == "push_contact" else 1.0,
            "scope": "unit probe only, not original clear_path task",
            "api_calls": 0,
            "code_sha256": {
                Path(m.__file__).name: audit.sha256(Path(m.__file__))
                for m in (
                    audit,
                    fixture,
                    push_probe,
                    groot_locomotion,
                    contact_probe,
                    contact_control,
                )
            },
            "cli_sha256": audit.sha256(Path(__file__)),
        }
        write(root / "protocol.json", protocol)
        result = contact_probe.run_probe(
            model,
            args.groot_root,
            root,
            kind=args.kind,
            duration=duration,
            initial_y=args.initial_y,
        )
        write(root / "result.json", result)
        report = f"""<!doctype html><html lang='ko'><meta charset='utf-8'>
<title>실제 물리 밀기 단위 시험</title><style>
body{{max-width:1000px;margin:30px auto;font-family:sans-serif;line-height:1.6}}
video,img{{max-width:100%}}pre{{white-space:pre-wrap}}</style>
<h1>실제 물리 시험: {args.kind}</h1>
<p>CUDA 보행 + 팔 목표 제어. GPT 호출 없음.<br>
전체 상자 제거/통과 과제의 성공은 아직 평가하지 않습니다.</p>
<h2>단위 시험 성공: {result["probe_success"]} / 종료: {result["termination_reason"]}</h2>
<p>상자 이동(m): {result["box_displacement_xyz_m"]}.<br>
손 접촉 step: {result["hand_contact_steps"]}. 손 회수: {result["released"]}.</p>
<video controls src='rollout.mp4'></video><p><a href='rollout.gif'>실제 실행 GIF</a></p>
<p>push_contact는 상자 가까이에서 시작하는 전방 밀기 단위 시험입니다.
원래 출발점부터 접근하거나 옆 공간으로 치워서 통과한 결과가 아닙니다.</p>
<details><summary>측정 결과</summary>
<pre>{html.escape(json.dumps(result, indent=2))}</pre></details>
<p><a href='contacts.jsonl'>접촉 기록</a> · <a href='state_trajectory.jsonl'>상태/제어 기록</a>
 · <a href='protocol.json'>실행 조건</a></p></html>"""
        with (root / "report.html").open("x") as f:
            f.write(report)
        write(
            root / "manifest.json",
            {
                "artifacts": [
                    {"path": q.name, "sha256": audit.sha256(q), "size_bytes": q.stat().st_size}
                    for q in sorted(root.iterdir())
                    if q.is_file()
                ]
            },
        )
        print(
            f"RESULT={root / 'result.json'}; success={result['probe_success']}; "
            f"reason={result['termination_reason']}",
            flush=True,
        )
    except Exception as exc:
        # This runner performs no API calls; local diagnostic message contains no auth header.
        write(
            root / "error.json",
            {
                "stage": "local_probe",
                "type": type(exc).__name__,
                "message": str(exc)[:1500],
                "clear_path_success": None,
            },
        )
        print(f"Probe error: {type(exc).__name__}; see {root / 'error.json'}", flush=True)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
