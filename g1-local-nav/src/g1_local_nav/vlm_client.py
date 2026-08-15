"""HTTP client for the VLM server (blueprint §11). Talks to the separately-running FastAPI
process (services/vlm_server/app.py) over local HTTP — never imports that package directly.
This runs in the g1-sim venv; the server runs in g1-vlm (blueprint §5.1 process isolation).

Timeouts and connection errors are NOT swallowed here — decide() raises, and the caller
(control_loop.py) is responsible for treating any exception as a STOP (blueprint §12.1: "VLM
timeout은 STOP으로 처리한다"). Keeping that policy at the control-loop level, not buried in the
client, matches how the reference algorithm in the blueprint is written.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import httpx
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class VlmDecision:
    action: str
    raw_text: str
    latency_ms: float
    parse_ok: bool


class VlmClient:
    def __init__(self, base_url: str, timeout_s: float = 8.0):
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    async def health(self) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            resp = await client.get(f"{self._base_url}/health")
            resp.raise_for_status()
            return resp.json()

    async def decide(
        self,
        image: np.ndarray,
        instruction: str,
        episode_id: str,
        step_index: int,
        previous_action: str | None = None,
        timeout_s: float | None = None,
    ) -> VlmDecision:
        buf = io.BytesIO()
        Image.fromarray(image).convert("RGB").save(buf, format="JPEG")
        image_bytes = buf.getvalue()

        data = {
            "instruction": instruction,
            "episode_id": episode_id,
            "step_index": str(step_index),
        }
        if previous_action is not None:
            data["previous_action"] = previous_action
        files = {"image": ("frame.jpg", image_bytes, "image/jpeg")}

        async with httpx.AsyncClient(timeout=timeout_s or self._timeout_s) as client:
            resp = await client.post(
                f"{self._base_url}/v1/navigation-action", data=data, files=files
            )
            resp.raise_for_status()
            body = resp.json()

        return VlmDecision(
            action=body["action"],
            raw_text=body["raw_text"],
            latency_ms=body["latency_ms"],
            parse_ok=body["parse_ok"],
        )


class FakeVlmClient:
    """Scripted decisions, no HTTP/model involved (blueprint §18.2 "Fake VLM server + real
    simulator", §18.3 oracle policy). Same decide() shape as VlmClient — control_loop.py takes
    either behind VlmClientProtocol. Used both by the mocked control-loop unit test and by
    `cli.py --policy fake` for interactively exercising the real simulator without needing the
    VLM server process running.
    """

    def __init__(self, script: list[str] | None = None):
        self._script = script or ["FORWARD", "FORWARD", "TURN_LEFT", "FORWARD", "STOP"]
        self._index = 0

    async def decide(
        self,
        image,
        instruction: str,
        episode_id: str,
        step_index: int,
        previous_action: str | None = None,
        timeout_s: float | None = None,
    ) -> VlmDecision:
        action = self._script[self._index % len(self._script)]
        self._index += 1
        return VlmDecision(action=action, raw_text=action, latency_ms=1.0, parse_ok=True)
