"""CLI entry point for the closed-loop episode (blueprint §6, §17 Milestone 5).

Must run under `mjpython`, not plain `python` — same macOS MuJoCo constraint as every other
script that touches G1Runtime (see envs/SETUP_NOTES.md).

For --policy real, the VLM server must already be running as its own process
(`uvicorn services.vlm_server.app:app` in the g1-vlm venv) — this CLI does not launch it,
matching blueprint §5.1's process separation. For --policy gpt, no local server/model is
needed at all — GptVlmClient calls the OpenAI API directly, reading OPENAI_API_KEY/
OPENAI_MODEL from a repo-root .env file (see scripts/diag_gpt_vision.py, which found the local
SmolVLM2-500M-Video-Instruct-mlx checkpoint doesn't ground image content at all — 100% wrong on
trivially easy synthetic color/left-right tests — while GPT-5 got every one right). For
--policy fake, no VLM of any kind is needed — useful for testing the real simulator + control
loop wiring in isolation.

The scene's elastic band (suspends the robot at spawn) still needs a manual "9" keypress by
default — an --auto-release-band option exists (see G1Runtime.release_elastic_band()) but
isn't the default yet: an earlier, faster version of it made the robot fall before the episode's
first decision on its very first live run. It's been slowed down since but not yet re-confirmed
live, so it stays opt-in.

Usage (run as a script path, not `-m` — see envs/SETUP_NOTES.md for why `-m` doesn't work
without a proper package install):
  export CYCLONEDDS_HOME="$(pwd)/third_party/cyclonedds-c/install"
  export SDL_VIDEODRIVER=dummy
  mjpython src/g1_local_nav/cli.py --policy fake
  mjpython src/g1_local_nav/cli.py --policy real   # needs the local VLM server running separately
  mjpython src/g1_local_nav/cli.py --policy gpt    # needs .env with OPENAI_API_KEY/OPENAI_MODEL
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import typer

from lerobot.cameras.zmq.configuration_zmq import ZMQCameraConfig

from g1_local_nav.action_mapper import ActionMapper
from g1_local_nav.config import DEFAULT_CONFIG_PATH, AppConfig, load_config
from g1_local_nav.control_loop import run_episode
from g1_local_nav.recorder import Recorder
from g1_local_nav.robot_runtime import G1Runtime
from g1_local_nav.vlm_client import FakeVlmClient, GptVlmClient, VlmClient

app = typer.Typer()


def _build_camera_config(config: AppConfig) -> ZMQCameraConfig:
    return ZMQCameraConfig(
        server_address=config.robot.camera_server_address,
        port=config.robot.camera_port,
        camera_name=config.robot.camera_name,
        width=config.robot.camera_width,
        height=config.robot.camera_height,
        fps=config.robot.camera_fps,
        warmup_s=config.robot.camera_warmup_s,
    )


@app.command()
def closed_loop(
    policy: str = typer.Option(
        "fake", help="'real' (local VLM server), 'gpt' (OpenAI API, .env), or 'fake' (scripted)"
    ),
    config_path: str = typer.Option(str(DEFAULT_CONFIG_PATH)),
    episode_id: str = typer.Option("ep0001"),
    auto_release_band: bool = typer.Option(
        False,
        help="Automatically lower and disable the scene's elastic band (mirrors pressing '7' "
        "several times then '9' in the MuJoCo window) instead of requiring a manual keypress — "
        "see G1Runtime.release_elastic_band(). Defaults to False: an earlier, faster version of "
        "this (10 steps * 0.15s = 1.5s total) made the robot topple over before the episode's "
        "first decision on the very first live run — fixed to ~8s total (matching the known-good "
        "settle_s=8.0 manual timing), but not yet re-confirmed live, so this stays opt-in rather "
        "than forced back on as the default (see conversation record).",
    ),
    settle_s: float = typer.Option(
        8.0,
        help="Used when --auto-release-band is NOT set (the default): wait this long after "
        "connect() for a manual '9' keypress in the MuJoCo window before the episode's safety "
        "checks start. Real deployments without this test-only elastic band can set this to 0.",
    ),
    lateral_offset_m: float = typer.Option(
        0.0,
        help="Spawn the robot this many meters to the left(+)/right(-) of the scene's default "
        "y=0 spawn (blueprint §17 Milestone 6: 3 initial left/right offsets). Applied right "
        "after connect(), before the settle wait — see G1Runtime.set_lateral_offset().",
    ),
    fake_script: str = typer.Option(
        "",
        help="Comma-separated NavAction tokens for --policy fake, e.g. "
        "'FORWARD,FORWARD,GRASP,TURN_LEFT,FORWARD,RELEASE' — lets a scripted run exercise "
        "GRASP/RELEASE through the real control_loop.py + G1Runtime (not just the default "
        "locomotion-only script). Ignored for --policy real. Empty means FakeVlmClient's own "
        "default script.",
    ),
) -> None:
    if policy not in ("real", "gpt", "fake"):
        typer.echo(f"--policy must be 'real', 'gpt', or 'fake', got {policy!r}", err=True)
        raise typer.Exit(code=1)

    config = load_config(config_path)
    camera_config = _build_camera_config(config)
    runtime = G1Runtime(
        camera_name=config.robot.camera_name,
        cameras={config.robot.camera_name: camera_config},
    )

    if policy == "fake":
        script = [tok.strip() for tok in fake_script.split(",") if tok.strip()] or None
        vlm_client = FakeVlmClient(script=script)
    elif policy == "gpt":
        vlm_client = GptVlmClient()
    else:
        vlm_client = VlmClient(base_url=config.vlm.base_url, timeout_s=config.vlm.timeout_s)
    action_mapper = ActionMapper()
    recorder = Recorder(
        config.logging.root_dir, episode_id, save_all_frames=config.logging.save_all_frames,
    )

    print(f"policy={policy} instruction={config.task.instruction!r} logs={recorder.run_dir}", flush=True)

    with runtime:
        if lateral_offset_m != 0.0:
            applied = runtime.set_lateral_offset(lateral_offset_m)
            print(
                f"lateral_offset_m={lateral_offset_m}: "
                f"{'applied' if applied else 'NOT applied — sim internals unreachable'}",
                flush=True,
            )
        if auto_release_band:
            released = runtime.release_elastic_band()
            print(
                f"elastic band auto-release: {'done' if released else 'NOT applied — sim internals unreachable'}",
                flush=True,
            )
        elif settle_s > 0:
            print(f"Waiting {settle_s}s for the MuJoCo window — release the elastic band (press 9) now.", flush=True)
            time.sleep(settle_s)
        result = asyncio.run(run_episode(runtime, vlm_client, config, action_mapper, recorder))

    typer.echo(f"Episode result: {result.outcome} ({result.reason})")
    typer.echo(f"Logs: {recorder.run_dir}")


if __name__ == "__main__":
    app()
