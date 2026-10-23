"""AFS-only OpenRouter wire adapter. Fixed endpoint, no retries or credential persistence."""

import os
from copy import deepcopy

import httpx

from robot_vlm import openrouter as wire

MODEL = "openai/gpt-6-luna-pro"


def require_key():
    key = os.environ.get(wire.KEY_ENV)
    if not key:
        raise ValueError("Set OPENROUTER_API_KEY in your terminal before --live")
    return key


def request_body(body):
    value = deepcopy(body)
    value.pop("service_tier", None)
    for message in value["input"]:
        if isinstance(message["content"], str):
            message["content"] = [{"type": "input_text", "text": message["content"]}]
    return wire.request_body(value)


def call(body, *, transport=None, timeout=300):
    if body.get("model") != MODEL or body.get("provider") != wire.ROUTING:
        raise ValueError("unexpected OpenRouter model/routing")
    key = require_key()
    with httpx.Client(transport=transport, timeout=timeout, follow_redirects=False) as client:
        try:
            response = client.post(
                wire.ENDPOINT, json=body, headers={"Authorization": "Bearer " + key}
            )
        except httpx.HTTPError:
            raise RuntimeError("OpenRouter transport failed; usage unknown; no resend") from None
    if response.status_code != 200:
        raise RuntimeError(f"OpenRouter HTTP {response.status_code}; no resend")
    # Return raw response for durable storage BEFORE interpreting finish/schema/model.
    return response.json()


def normalize(value):
    if value.get("error"):
        raise ValueError("OpenRouter returned an error; raw response preserved")
    if value.get("model") != MODEL:
        raise ValueError("OpenRouter returned an unexpected model; no fallback accepted")
    return wire.response_value(value)
