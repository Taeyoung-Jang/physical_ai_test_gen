"""CLI entry point for the closed-loop episode (blueprint §6, §17 Milestone 5).

Must run under `mjpython`, not plain `python` — same macOS MuJoCo constraint as every other
script that touches G1Runtime (see envs/SETUP_NOTES.md).

For --policy real, the VLM server must already be running as its own process
(`uvicorn services.vlm_server.app:app` in the g1-vlm venv) — this CLI does not launch it,
matching blueprint §5.1's process separation. For --policy fake, no VLM server is needed at
all — useful for testing the real simulator + control loop wiring in isolation.

Usage (run as a script path, not `-m` — see envs/SETUP_NOTES.md for why `-m` doesn't work
without a proper package install):
  export CYCLONEDDS_HOME="$(pwd)/third_party/cyclonedds-c/install"
  export SDL_VIDEODRIVER=dummy
  mjpython src/g1_local_nav/cli.py --policy fake
  mjpython src/g1_local_nav/cli.py --policy real   # needs the VLM server running separately
"""
from __future__ import annotations

import asyncio
import logging
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
from g1_local_nav.vlm_client import FakeVlmClient, VlmClient

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
    policy: str = typer.Option("fake", help="'real' (VLM server) or 'fake' (scripted, no HTTP)"),
    config_path: str = typer.Option(str(DEFAULT_CONFIG_PATH)),
    episode_id: str = typer.Option("ep0001"),
    settle_s: float = typer.Option(
        8.0,
        help="Wait this long after connect() before the episode's safety checks start. The "
        "test scene's elastic band holds the robot suspended by default and needs a manual "
        "'9' keypress in the MuJoCo window to release — without this delay, the very first "
        "safety check can fire on a spawn/settling transient before that keypress ever "
        "happens (seen in practice: pitch_exceeded at episode_duration_s=0.002, 0 VLM "
        "decisions). Real deployments without this test-only elastic band can set this to 0.",
    ),
) -> None:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("cli")

    if policy not in ("real", "fake"):
        typer.echo(f"--policy must be 'real' or 'fake', got {policy!r}", err=True)
        raise typer.Exit(code=1)

    config = load_config(config_path)
    camera_config = _build_camera_config(config)
    runtime = G1Runtime(
        camera_name=config.robot.camera_name,
        cameras={config.robot.camera_name: camera_config},
    )

    vlm_client = FakeVlmClient() if policy == "fake" else VlmClient(
        base_url=config.vlm.base_url, timeout_s=config.vlm.timeout_s,
    )
    action_mapper = ActionMapper()
    recorder = Recorder(
        config.logging.root_dir, episode_id, save_all_frames=config.logging.save_all_frames,
    )

    logger.info(f"policy={policy} instruction={config.task.instruction!r} logs={recorder.run_dir}")

    with runtime:
        if settle_s > 0:
            logger.info(f"Waiting {settle_s}s for the MuJoCo window — release the elastic band (press 9) now.")
            time.sleep(settle_s)
        result = asyncio.run(run_episode(runtime, vlm_client, config, action_mapper, recorder))

    typer.echo(f"Episode result: {result.outcome} ({result.reason})")
    typer.echo(f"Logs: {recorder.run_dir}")


if __name__ == "__main__":
    app()
