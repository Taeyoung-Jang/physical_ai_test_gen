"""Loads prompts/red_box_navigation.txt and fills in the instruction (blueprint §11.3)."""
from __future__ import annotations

from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "red_box_navigation.txt"


def build_prompt(instruction: str) -> str:
    return PROMPT_PATH.read_text().format(instruction=instruction)
