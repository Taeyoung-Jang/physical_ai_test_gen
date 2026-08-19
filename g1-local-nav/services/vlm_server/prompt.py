"""Loads prompts/red_box_navigation.txt and fills in the instruction (blueprint §11.3), plus the
previous action (pick-and-carry extension beyond blueprint §14) — GRASP/RELEASE decisions need
state the current image alone doesn't carry (e.g. "did I already grasp the box?"); previous_action
is the only such signal available to the model, since there's no separate success/failure field
in the request.
"""
from __future__ import annotations

from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "red_box_navigation.txt"


def build_prompt(instruction: str, previous_action: str | None = None) -> str:
    return PROMPT_PATH.read_text().format(
        instruction=instruction, previous_action=previous_action or "none (first step)"
    )
