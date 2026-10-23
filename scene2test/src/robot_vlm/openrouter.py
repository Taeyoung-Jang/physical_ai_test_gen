"""Explicit Chat Completions adapter; common strict robot action parser is retained."""

from copy import deepcopy

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
KEY_ENV = "OPENROUTER_API_KEY"
ROUTING = {"allow_fallbacks": False, "require_parameters": True}


def request_body(body):
    if "service_tier" in body:
        raise ValueError("OpenRouter requires service_tier to be omitted")
    if not isinstance(body.get("model"), str) or "/" not in body["model"]:
        raise ValueError("OpenRouter requires a provider/model ID")
    messages = []
    if body.get("instructions"):
        messages.append({"role": "system", "content": body["instructions"]})
    for message in body["input"]:
        parts = []
        for part in message["content"]:
            if part["type"] == "input_text":
                parts.append({"type": "text", "text": part["text"]})
            elif part["type"] == "input_image":
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": part["image_url"],
                            "detail": part.get("detail", "high"),
                        },
                    }
                )
            else:
                raise ValueError("unsupported OpenRouter input content")
        messages.append({"role": message["role"], "content": parts})
    fmt = body["text"]["format"]
    if fmt["type"] != "json_schema" or fmt.get("strict") is not True:
        raise ValueError("strict JSON schema required")
    result = {
        "model": body["model"],
        "messages": messages,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {key: deepcopy(fmt[key]) for key in ("name", "strict", "schema")},
        },
        "provider": dict(ROUTING),
    }
    if "reasoning" in body:
        result["reasoning"] = deepcopy(body["reasoning"])
    if "max_output_tokens" in body:
        result["max_tokens"] = body["max_output_tokens"]
    return result


def normalized_usage(value):
    usage = value.get("usage")
    if not isinstance(usage, dict):
        return None
    return {
        dst: usage[src]
        for src, dst in (
            ("prompt_tokens", "input_tokens"),
            ("completion_tokens", "output_tokens"),
            ("total_tokens", "total_tokens"),
        )
        if type(usage.get(src)) is int and usage[src] >= 0
    }


def response_value(value):
    """Normalize wire shape only; never repair output JSON or synthesize an action."""
    choices = value.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("exactly one OpenRouter choice required")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise ValueError("assistant message required")
    stopped = choice.get("finish_reason") == "stop" and not message.get("tool_calls")
    if message.get("refusal"):
        part = {"type": "refusal"}
    else:
        part = {"type": "output_text", "text": message.get("content")}
    return {
        "id": value.get("id"),
        "model": value.get("model"),
        "service_tier": value.get("service_tier"),
        "status": "completed" if stopped else "incomplete",
        "incomplete_details": {
            "reason": "max_output_tokens" if choice.get("finish_reason") == "length" else None
        },
        "usage": normalized_usage(value),
        "output": [{"type": "message", "role": "assistant", "content": [part]}],
    }
