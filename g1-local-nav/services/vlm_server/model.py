"""Loads SmolVLM2 via MLX and runs single-image navigation-action inference.

The load() -> apply_chat_template() -> generate() call pattern here is verified against
mlx_vlm.chat.ChatSession.generate_response() (the library's own reference single/multi-turn
image+text usage), not guessed from the public API's type hints alone — mlx_vlm's generate()
takes image paths, not raw arrays, hence the temp-file round-trip in infer().
"""
from __future__ import annotations

import tempfile
import time

from mlx_vlm import apply_chat_template, generate, load
from PIL import Image

DEFAULT_MODEL_ID = "mlx-community/SmolVLM2-500M-Video-Instruct-mlx"


class VlmModel:
    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        max_tokens: int = 8,
        temperature: float = 0.0,
    ):
        self.model_id = model_id
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._model = None
        self._processor = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        self._model, self._processor = load(self.model_id)

    def infer(self, image: Image.Image, prompt_text: str) -> tuple[str, float]:
        """Runs one forward pass. Returns (raw_text, latency_ms)."""
        if not self.loaded:
            raise RuntimeError("model not loaded — call load() first")

        prompt = apply_chat_template(
            self._processor, self._model.config, prompt_text, num_images=1,
        )

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=True) as tmp:
            image.convert("RGB").save(tmp.name)
            t0 = time.monotonic()
            result = generate(
                self._model,
                self._processor,
                prompt,
                image=[tmp.name],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                verbose=False,
            )
            latency_ms = (time.monotonic() - t0) * 1000

        return result.text, latency_ms
