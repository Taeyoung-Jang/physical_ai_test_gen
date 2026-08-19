"""Unit tests for the VLM server's strict action parser (blueprint §18.1)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from services.vlm_server.parser import parse_action


@pytest.mark.parametrize("token", ["FORWARD", "BACKWARD", "TURN_LEFT", "TURN_RIGHT", "STOP", "GRASP", "RELEASE"])
def test_exact_match(token: str) -> None:
    action, ok = parse_action(token)
    assert (action, ok) == (token, True)


@pytest.mark.parametrize(
    "raw",
    ["  forward  ", "'FORWARD'", '"FORWARD"', "```\nFORWARD\n```", "```text\nFORWARD```", "forward\n"],
)
def test_whitespace_quotes_and_code_fences_stripped(raw: str) -> None:
    action, ok = parse_action(raw)
    assert (action, ok) == ("FORWARD", True)


def test_single_token_embedded_in_sentence_extracted() -> None:
    action, ok = parse_action("I think the robot should choose TURN_LEFT here.")
    assert (action, ok) == ("TURN_LEFT", True)


def test_grasp_embedded_in_sentence_extracted() -> None:
    action, ok = parse_action("The box is close and centered, so GRASP now.")
    assert (action, ok) == ("GRASP", True)


def test_release_exact_match() -> None:
    action, ok = parse_action("RELEASE")
    assert (action, ok) == ("RELEASE", True)


def test_ambiguous_two_tokens_falls_back_to_stop() -> None:
    action, ok = parse_action("Either FORWARD or TURN_LEFT could work.")
    assert (action, ok) == ("STOP", False)


def test_unknown_output_falls_back_to_stop() -> None:
    action, ok = parse_action("I am not sure what to do.")
    assert (action, ok) == ("STOP", False)


def test_empty_string_falls_back_to_stop() -> None:
    action, ok = parse_action("")
    assert (action, ok) == ("STOP", False)


def test_substring_does_not_falsely_match() -> None:
    # "STOPPING" contains "STOP" as a substring but not as a whole word — must not match.
    action, ok = parse_action("STOPPING now due to danger")
    assert (action, ok) == ("STOP", False)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
