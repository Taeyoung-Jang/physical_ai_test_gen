"""Episode-local downgrade on verified length only; every attempt spends call budget."""

MODEL = "openai/gpt-6-luna"
EFFORTS = ("high", "medium", "low", "none")
WALL_DEADLINE_S = 1200.0


def eligible(provider, model):
    return provider == "openrouter" and model == MODEL


def contract(enabled):
    return {
        "version": "verified-length-reasoning-fallback-v1",
        "enabled": enabled,
        "efforts": list(EFFORTS) if enabled else [],
        "trigger": "HTTP 200, requested Luna model, api_incomplete_response/max_output_tokens",
        "budget": "each generation consumes one of the existing episode robot API calls",
        "scope": "start high each episode, retain reduced effort until episode ends",
        "observation": "refresh scene/image for next attempt; never execute truncated output",
        "http_or_timeout_or_schema_retry": False,
        "per_attempt_wall_deadline_s": WALL_DEADLINE_S if enabled else None,
    }


def next_effort(exc, current):
    from .api_transport import DiagnosticError

    if not isinstance(exc, DiagnosticError):
        return None
    d = exc.diagnostic
    if (
        d.get("code") != "api_incomplete_response"
        or d.get("incomplete_reason") != "max_output_tokens"
        or d.get("http_status") != 200
        or d.get("returned_model") != MODEL
        or current not in EFFORTS[:-1]
    ):
        return None
    return EFFORTS[EFFORTS.index(current) + 1]


def deadline(timing, enabled):
    return max(timing.deadline_s, WALL_DEADLINE_S) if enabled else timing.deadline_s
