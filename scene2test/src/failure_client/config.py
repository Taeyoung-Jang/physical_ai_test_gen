"""Client runtime settings loaded without persisting secrets."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .api.http_gateway import HttpGatewayConfig


@dataclass(frozen=True, slots=True)
class ClientSettings:
    server_url: str
    workspace_dir: Path
    bearer_token: str | None = None
    timeout_s: float = 30.0
    max_attempts: int = 3

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ClientSettings:
        values = os.environ if env is None else env
        server_url = values.get("FAILURE_CLIENT_SERVER_URL", "").strip()
        if not server_url:
            raise ValueError("FAILURE_CLIENT_SERVER_URL is required")
        workspace = Path(values.get("FAILURE_CLIENT_WORKSPACE", "workspace")).expanduser()
        token = values.get("FAILURE_CLIENT_TOKEN") or None
        return cls(
            server_url=server_url,
            workspace_dir=workspace,
            bearer_token=token,
            timeout_s=float(values.get("FAILURE_CLIENT_TIMEOUT_S", "30")),
            max_attempts=int(values.get("FAILURE_CLIENT_MAX_ATTEMPTS", "3")),
        )

    @property
    def database_path(self) -> Path:
        return self.workspace_dir / "client.sqlite"

    @property
    def artifact_dir(self) -> Path:
        return self.workspace_dir / "artifacts"

    def gateway_config(self) -> HttpGatewayConfig:
        return HttpGatewayConfig(
            base_url=self.server_url,
            artifact_dir=self.artifact_dir,
            bearer_token=self.bearer_token,
            timeout_s=self.timeout_s,
            max_attempts=self.max_attempts,
        )

    def __repr__(self) -> str:
        return (
            "ClientSettings("
            f"server_url={self.server_url!r}, workspace_dir={self.workspace_dir!r}, "
            f"bearer_token={'***' if self.bearer_token else None}, "
            f"timeout_s={self.timeout_s!r}, max_attempts={self.max_attempts!r})"
        )

