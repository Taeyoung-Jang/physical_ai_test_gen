"""VLM server (blueprint §11) — FastAPI app exposing /health and /v1/navigation-action.

Runs in the g1-vlm venv, fully decoupled from the simulator process (blueprint §5.1). The
model loads once at startup (not per-request) and stays warm.

Usage:
  uvicorn services.vlm_server.app:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import io
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, UploadFile
from PIL import Image

from .model import DEFAULT_MODEL_ID, VlmModel
from .parser import parse_action
from .prompt import build_prompt
from .schemas import HealthResponse, NavigationActionResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vlm_server")

_model = VlmModel(model_id=DEFAULT_MODEL_ID)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Loading {_model.model_id}...")
    _model.load()
    logger.info("Model loaded.")
    yield


app = FastAPI(title="g1-local-nav VLM server", lifespan=lifespan)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", model_loaded=_model.loaded, model_id=_model.model_id)


@app.post("/v1/navigation-action", response_model=NavigationActionResponse)
async def navigation_action(
    image: UploadFile = File(...),
    instruction: str = Form(...),
    episode_id: str = Form(...),
    step_index: int = Form(...),
    previous_action: str | None = Form(None),
) -> NavigationActionResponse:
    img_bytes = await image.read()
    pil_image = Image.open(io.BytesIO(img_bytes))

    prompt_text = build_prompt(instruction, previous_action)
    raw_text, latency_ms = _model.infer(pil_image, prompt_text)
    action, parse_ok = parse_action(raw_text)

    logger.info(
        f"episode={episode_id} step={step_index} action={action} parse_ok={parse_ok} "
        f"latency_ms={latency_ms:.1f} raw={raw_text!r}"
    )

    return NavigationActionResponse(
        action=action,
        raw_text=raw_text,
        latency_ms=latency_ms,
        model_id=_model.model_id,
        parse_ok=parse_ok,
    )
