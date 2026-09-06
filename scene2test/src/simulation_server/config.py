from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SERVER_DATA_ROOT = Path("/workspace/g1_failure/runtime/server")


@dataclass(frozen=True, slots=True)
class ServerConfig:
    data_root: Path
    groot_root: Path
    worker_python: str = sys.executable
    api_key: str | None = None
    execution_backend: str = "groot_mujoco"
    maximum_episode_duration_s: float = 120.0
    maximum_interventions: int = 100
    worker_startup_grace_s: float = 120.0

    @classmethod
    def from_env(cls) -> "ServerConfig":
        workspace = Path(__file__).resolve().parents[4]
        return cls(
            data_root=Path(
                os.getenv("SIM_SERVER_DATA_ROOT", str(DEFAULT_SERVER_DATA_ROOT))
            ).resolve(),
            groot_root=Path(
                os.getenv("GROOT_WBC_ROOT", workspace / "GR00T-WholeBodyControl")
            ).resolve(),
            worker_python=os.getenv("GROOT_WBC_PYTHON", sys.executable),
            api_key=os.getenv("SIM_SERVER_API_KEY") or None,
            execution_backend=os.getenv("SIM_SERVER_BACKEND", "groot_mujoco"),
            worker_startup_grace_s=float(
                os.getenv("SIM_SERVER_WORKER_STARTUP_GRACE_S", "120")
            ),
        )

    def prepare(self) -> None:
        for relative in ("registries", "outputs/jobs", "db", "assets"):
            (self.data_root / relative).mkdir(parents=True, exist_ok=True)
