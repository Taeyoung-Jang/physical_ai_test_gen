"""Flushed per-call debug events without credentials or request bodies."""

import contextvars
import json
import os
import re
import time
import traceback
from datetime import datetime, timezone
from uuid import uuid4

CURRENT = contextvars.ContextVar("robot_debug", default=None)


def clean(value):
    value = str(value)
    key = os.getenv("OPENAI_API_KEY")
    if key:
        value = value.replace(key, "[REDACTED]")
    value = re.sub(r"(?i)Bearer\s+\S+|sk-[\w-]+", "[REDACTED]", value)
    return value[:2000]


def exception_detail(exc):
    chain, seen = [], set()
    while exc is not None and id(exc) not in seen and len(chain) < 8:
        seen.add(id(exc))
        chain.append(
            {
                "type": type(exc).__name__,
                "message": clean(exc),
                "frames": [
                    {"file": clean(f.filename), "line": f.lineno, "function": f.name}
                    for f in traceback.extract_tb(exc.__traceback__)
                ],
            }
        )
        exc = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
    return chain


class Journal:
    def __init__(self, path, version, *, read_timeout_s=30.0):
        self.path, self.version = path, version
        self.read_timeout_s = read_timeout_s
        self.client_request_id = str(uuid4())
        self.started = time.monotonic()

    def emit(self, event, **fields):
        value = {
            "utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_wall_s": time.monotonic() - self.started,
            "observation_version": self.version,
            "client_request_id": self.client_request_id,
            "event": event,
            **fields,
        }
        with self.path.open("a") as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")
            stream.flush()

    def decide(self, policy, observation, png):
        token = CURRENT.set(self)
        self.emit("policy_started")
        try:
            result = policy.decide(observation, png)
            self.emit("policy_completed")
            return result
        except Exception as exc:
            self.emit(
                "policy_failed",
                exception_chain=exception_detail(exc),
                diagnostic=getattr(exc, "diagnostic", None),
            )
            raise
        finally:
            CURRENT.reset(token)
