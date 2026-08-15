"""Strict parser (blueprint §11.2) — forces raw VLM output into exactly one of 4 allowed
action tokens, or STOP on any ambiguity/failure.

No imports from src/g1_local_nav here on purpose: the VLM server and the sim/control process
are meant to be fully decoupled (blueprint §5.1, "의존성 충돌과 장애 격리"), so the 4 valid
tokens are just redefined here rather than shared.
"""
from __future__ import annotations

import re

VALID_ACTIONS = ("FORWARD", "TURN_LEFT", "TURN_RIGHT", "STOP")

_CODE_FENCE_RE = re.compile(r"^```\w*\n?|```$", re.MULTILINE)


def parse_action(raw_text: str) -> tuple[str, bool]:
    """Parse raw model output into (action, parse_ok).

    Rules (blueprint §11.2):
      1. Strip whitespace, quotes, markdown code fences.
      2. Uppercase.
      3. Exact enum match wins immediately.
      4. If exactly one of the 4 tokens appears as a whole word anywhere, use it.
      5. Zero or 2+ matches => parse failure.
      6. Parse failure always resolves to ("STOP", False) — never left ambiguous.
    """
    cleaned = _CODE_FENCE_RE.sub("", raw_text).strip().strip("'\"").strip()
    upper = cleaned.upper()

    if upper in VALID_ACTIONS:
        return upper, True

    found = {a for a in VALID_ACTIONS if re.search(rf"\b{a}\b", upper)}
    if len(found) == 1:
        return next(iter(found)), True

    return "STOP", False
