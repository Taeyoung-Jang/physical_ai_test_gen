"""Human-readable fixture report. Static preview media are never labeled rollouts."""

import html
import json

import numpy as np

from .fixture import BOX_SIZE, BOX_TARGET, GOAL, SPAWN, WALLS


def plot_map(nav, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.imshow(
        nav["blocked"],
        origin="lower",
        extent=[-0.1, 8.1, -1, 2.7],
        cmap="Greys",
        alpha=0.35,
        vmin=0,
        vmax=1,
    )
    for a, b, c, d in WALLS.values():
        ax.add_patch(Rectangle((a, c), b - a, d - c, color="#334155"))
    bx, by = nav["box_xy_m"]
    ax.add_patch(
        Rectangle(
            (bx - 0.4, by - 0.55), BOX_SIZE[0], BOX_SIZE[1], color="#fb923c", label="Movable box"
        )
    )
    ax.add_patch(
        Rectangle(
            (BOX_TARGET[0] - 0.4, BOX_TARGET[1] - 0.55),
            0.8,
            1.1,
            fill=False,
            edgecolor="green",
            linestyle="--",
            label="Proposed box destination",
        )
    )
    ax.scatter(*SPAWN, color="green", label="Robot start")
    ax.scatter(*GOAL, color="blue", label="Robot goal")
    if nav["path_xy_m"]:
        points = np.asarray(nav["path_xy_m"])
        ax.plot(
            points[:, 0], points[:, 1], "b--", label="Geometric reference, NOT actual trajectory"
        )
    prefix = (
        "HYPOTHETICAL box placement - NOT executed"
        if nav["hypothetical"]
        else "INITIAL state - NOT a rollout"
    )
    ax.set(
        title=f"{prefix} | path exists: {nav['reachable']}",
        xlabel="World X (m)",
        ylabel="World Y (m)",
        aspect="equal",
    )
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def render(model, data, root):
    import imageio.v2 as imageio
    import mujoco
    from PIL import Image, ImageDraw

    camera = mujoco.MjvCamera()
    camera.lookat[:] = [4, 0.5, 0.2]
    camera.distance, camera.azimuth, camera.elevation = 9, -90, -55
    frames = []
    with mujoco.Renderer(model, height=540, width=960) as renderer:
        for i in range(36):
            camera.azimuth = -120 + i * 60 / 35
            renderer.update_scene(data, camera=camera)
            frame = Image.fromarray(renderer.render())
            draw = ImageDraw.Draw(frame)
            draw.rectangle((0, 0, 960, 35), fill="#0f172a")
            draw.text(
                (14, 12),
                "STATIC SCENE CAMERA PREVIEW | robot actions: 0 | simulation time: 0",
                fill="white",
            )
            frames.append(np.asarray(frame).copy())
        imageio.imwrite(root / "overview.png", frames[18])
        renderer.update_scene(data, camera="clear_robot_camera")
        imageio.imwrite(root / "robot_view.png", renderer.render())
    imageio.mimsave(root / "scene_preview.gif", frames, duration=1000 / 12, loop=0)
    with imageio.get_writer(root / "scene_preview.mp4", fps=12, macro_block_size=2) as writer:
        for frame in frames:
            writer.append_data(frame)
    return {
        "kind": "static_scene_camera_orbit",
        "robot_rollouts": 0,
        "physics_steps": 0,
        "frames": len(frames),
        "fps": 12,
        "camera_name": "clear_robot_camera",
        "note": "Robot view is a configured simulation camera, not a calibrated real sensor",
    }


def write_report(root, audit, render_status):
    media = (
        "<img src='overview.png'><video controls src='scene_preview.mp4'></video>"
        "<p><a href='scene_preview.gif'>GIF 열기</a> — 움직이는 것은 카메라뿐입니다.</p>"
        "<h2>로봇 위치의 시뮬레이션 카메라</h2><img src='robot_view.png'>"
        if render_status["status"] == "OK"
        else "<p>3D 렌더링 실패/미실행: " + html.escape(str(render_status)) + "</p>"
    )
    content = f"""<!doctype html><html lang='ko'><meta charset='utf-8'>
<title>Clear-path 환경 준비 보고서</title><style>
body{{max-width:1100px;margin:30px auto;padding:0 20px;font-family:sans-serif;line-height:1.65}}
img,video{{width:100%;border:1px solid #ddd}} .notice{{padding:20px;background:#fff3cd}}
pre{{white-space:pre-wrap}} </style>
<h1>상자를 밀어 길 열기 — 환경 준비 단계</h1>
<div class='notice'><b>로봇 실행 0회 · GPT 호출 0회 · 밀기 성공 미검증</b><br>
아래 MP4/GIF는 정지 장면을 둘러보는 미리보기입니다. 실제 로봇 행동 영상이 아닙니다.</div>
<p>주황색 상자가 통로를 막고 있습니다. 녹색 옆 공간으로 상자를 옮겨 길을 여는 것이
향후 과제입니다. 파란색 표식은 로봇의 최종 목적지입니다.</p>
{media}
<h2>현재 배치: 보행 경로 없음</h2><img src='map_initial.png'>
<h2>비교용 예상 배치: 상자가 옆 공간에 있다면</h2>
<p>아래 그림은 가정한 배치의 지도 계산일 뿐, 실제로 상자를 옮긴 결과가 아닙니다.
이 경로는 로봇이 상자를 밀 수 있음을 보장하지 않습니다.</p><img src='map_hypothetical.png'>
<h2>제어 점검</h2><p>로봇의 {audit["robot_actuators"]}개 actuator와 관절 주소는 보존되었습니다.
기존 보행 관측 벡터 비교: {audit["gait_observation_equal"]}.<br>
팔 제어/밀기 실행기는 아직 없습니다.</p>
<p>다음 관문: 손바닥 접촉을 이용한 팔 동작과 균형 유지, 실제 물체 이동을 검증한 뒤
GPT 행동 선택을 연결합니다.</p>
<h2>기록</h2><ul><li><a href='robot_audit.json'>관절·손 접촉·자원 점검</a></li>
<li><a href='scene_graph.json'>초기 SceneGraph</a></li><li><a href='status.json'>현재 상태</a></li>
<li><a href='manifest.json'>산출물 해시</a></li></ul>
<details><summary>미디어 상태</summary>
<pre>{html.escape(json.dumps(render_status, indent=2))}</pre></details>
</html>"""
    with (root / "report.html").open("x") as f:
        f.write(content)
