"""Integration tests for the VLM server API (blueprint §18.2 "Real VLM server + saved frame").

Uses a fake VlmModel (no MLX/model download) so these run fast and deterministically — the
real model is exercised manually (see runs/ from the Milestone 4 smoke test), not here. This
covers Milestone 4's completion criteria around malformed-output handling and response schema,
independent of any particular model's actual accuracy (blueprint §17: "정확도는 첫 완료 조건이
아니다").
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import services.vlm_server.app as app_module


class FakeVlmModel:
    """Stands in for VlmModel — returns a scripted raw_text without loading anything."""

    def __init__(self, raw_text: str = "FORWARD"):
        self.model_id = "fake-model"
        self.raw_text = raw_text
        self._loaded = True

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        self._loaded = True

    def infer(self, image, prompt_text):
        return self.raw_text, 12.3


def _fake_image_bytes() -> bytes:
    img = Image.new("RGB", (64, 48), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def client(monkeypatch):
    fake = FakeVlmModel()
    monkeypatch.setattr(app_module, "_model", fake)
    with TestClient(app_module.app) as c:
        yield c, fake


def _post_action(client: TestClient, **overrides) -> dict:
    data = {
        "instruction": "Move toward the red box and stop near it.",
        "episode_id": "test_ep",
        "step_index": "0",
        **overrides,
    }
    files = {"image": ("frame.jpg", _fake_image_bytes(), "image/jpeg")}
    resp = client.post("/v1/navigation-action", data=data, files=files)
    assert resp.status_code == 200
    return resp.json()


def test_health(client) -> None:
    c, fake = client
    resp = c.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "model_loaded": True, "model_id": "fake-model"}


def test_valid_action_passthrough(client) -> None:
    c, fake = client
    fake.raw_text = "TURN_LEFT"
    body = _post_action(c)
    assert body["action"] == "TURN_LEFT"
    assert body["parse_ok"] is True
    assert body["raw_text"] == "TURN_LEFT"
    assert body["latency_ms"] == 12.3


@pytest.mark.parametrize(
    "malformed_raw",
    [
        "I'm not sure, maybe FORWARD or TURN_LEFT?",  # ambiguous
        "The robot should proceed carefully.",  # no token at all
        "",  # empty
        "FORWARD TURN_LEFT TURN_RIGHT",  # everything at once
    ],
)
def test_malformed_output_falls_back_to_stop(client, malformed_raw: str) -> None:
    c, fake = client
    fake.raw_text = malformed_raw
    body = _post_action(c)
    assert body["action"] == "STOP"
    assert body["parse_ok"] is False


def test_missing_required_field_rejected(client) -> None:
    c, _ = client
    files = {"image": ("frame.jpg", _fake_image_bytes(), "image/jpeg")}
    # instruction omitted — required field
    resp = c.post(
        "/v1/navigation-action",
        data={"episode_id": "e", "step_index": "0"},
        files=files,
    )
    assert resp.status_code == 422


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
