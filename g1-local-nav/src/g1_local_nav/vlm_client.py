"""HTTP client for the VLM server (blueprint §11). Talks to the separately-running FastAPI
process (services/vlm_server/app.py) over local HTTP — never imports that package directly.
This runs in the g1-sim venv; the server runs in g1-vlm (blueprint §5.1 process isolation).

Timeouts and connection errors are NOT swallowed here — decide() raises, and the caller
(control_loop.py) is responsible for treating any exception as a STOP (blueprint §12.1: "VLM
timeout은 STOP으로 처리한다"). Keeping that policy at the control-loop level, not buried in the
client, matches how the reference algorithm in the blueprint is written.
"""
from __future__ import annotations

import base64
import io
import re
import time
from dataclasses import dataclass
from pathlib import Path

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


_VALID_ACTIONS = ("FORWARD", "BACKWARD", "TURN_LEFT", "TURN_RIGHT", "STOP", "GRASP", "RELEASE")
_CODE_FENCE_RE = re.compile(r"^```\w*\n?|```$", re.MULTILINE)
_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "red_box_navigation.txt"
_DEFAULT_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


def _build_prompt(instruction: str, previous_action: str | None) -> str:
    return _PROMPT_PATH.read_text().format(
        instruction=instruction, previous_action=previous_action or "none (first step)"
    )


def _parse_action(raw_text: str) -> tuple[str, bool]:
    """Same rules as services/vlm_server/parser.py's parse_action(), duplicated rather than
    imported — that module deliberately has zero g1_local_nav dependencies so it can run in a
    fully separate venv/process (blueprint §5.1), and this class runs in the opposite direction
    (g1-sim venv calling out to a cloud API, no local model process at all), so importing across
    that boundary would mean relying on the repo root being on sys.path, which isn't guaranteed
    for every entry point (see cli.py's sys.path.insert, which only adds src/, not the repo
    root). ~15 lines duplicated is simpler and more robust than fixing that for one import.
    """
    cleaned = _CODE_FENCE_RE.sub("", raw_text).strip().strip("'\"").strip()
    upper = cleaned.upper()
    if upper in _VALID_ACTIONS:
        return upper, True
    found = {a for a in _VALID_ACTIONS if re.search(rf"\b{a}\b", upper)}
    if len(found) == 1:
        return next(iter(found)), True
    return "STOP", False


def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


class GptVlmClient:
    """Calls the OpenAI API directly instead of the local g1-vlm server/MLX model — the
    pick-and-carry extension's diagnostic (scripts/diag_gpt_vision.py) found that the local
    SmolVLM2-500M-Video-Instruct-mlx checkpoint answered identically regardless of image content
    (100% wrong on trivially easy synthetic color/left-right tests), while GPT-5 got every one
    of the same tests right against the same images. Same decide() shape as VlmClient/
    FakeVlmClient — control_loop.py takes any of the three behind VlmClientProtocol. No local
    VLM server process needed for this policy; reads OPENAI_API_KEY/OPENAI_MODEL from a
    repo-root .env file (gitignored, never logged) instead.
    """

    API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        env_path: Path | str = _DEFAULT_ENV_PATH,
    ):
        env = _load_env(Path(env_path))
        self._api_key = api_key or env.get("OPENAI_API_KEY")
        self._model = model or env.get("OPENAI_MODEL", "gpt-5")
        if not self._api_key:
            raise ValueError(f"OPENAI_API_KEY not found in {env_path} (and none passed explicitly)")

    async def decide(
        self,
        image: np.ndarray,
        instruction: str,
        episode_id: str,
        step_index: int,
        previous_action: str | None = None,
        timeout_s: float | None = None,
    ) -> VlmDecision:
        prompt_text = _build_prompt(instruction, previous_action)

        buf = io.BytesIO()
        Image.fromarray(image).convert("RGB").save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=timeout_s or 30.0) as client:
            resp = await client.post(
                self.API_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt_text},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                                },
                            ],
                        }
                    ],
                    # reasoning_effort="none": this is a trivial single-token classification,
                    # not a task that benefits from extended reasoning — and reasoning tokens
                    # count against max_completion_tokens without appearing in the visible
                    # content. At the default effort, all 16 budgeted tokens went to hidden
                    # reasoning and the API returned finish_reason="length" with an EMPTY
                    # content string (silently defaulting to STOP via _parse_action's failure
                    # path) — see conversation record. "none" fixed it: 0 reasoning tokens,
                    # ~0.9s latency, correct answer.
                    "reasoning_effort": "none",
                    "max_completion_tokens": 300,
                },
            )
            resp.raise_for_status()
            body = resp.json()
        latency_ms = (time.monotonic() - t0) * 1000

        raw_text = body["choices"][0]["message"]["content"]
        action, parse_ok = _parse_action(raw_text)

        return VlmDecision(action=action, raw_text=raw_text, latency_ms=latency_ms, parse_ok=parse_ok)
