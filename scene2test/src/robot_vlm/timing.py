"""Explicit goal-agent request timing; simulation budget is independent."""

import math
from dataclasses import dataclass

CONNECT_RETRIES = 2
CONNECT_RETRY_DELAYS_S = (1.0, 2.0)


def connection_retry_contract():
    return {
        "version": "pre-send-tcp-retry-v1",
        "max_retries": CONNECT_RETRIES,
        "backoff_s": list(CONNECT_RETRY_DELAYS_S),
        "eligibility": "ConnectError/ConnectTimeout with traced connect_tcp.failed and no send",
        "ambiguous_or_post_send_retry": False,
        "accounting": "connection attempts within one policy call, not extra robot actions",
    }


@dataclass(frozen=True)
class RequestTiming:
    read_s: float = 90.0

    def __post_init__(self):
        if not math.isfinite(self.read_s) or not 1 <= self.read_s <= 600:
            raise ValueError("response-timeout must be finite, 1..600 seconds")

    @property
    def deadline_s(self):
        # Connect/write/pool timeout allowances and scheduling/parse margin.
        return self.read_s + 30.0 + CONNECT_RETRIES * 10 + sum(CONNECT_RETRY_DELAYS_S)
