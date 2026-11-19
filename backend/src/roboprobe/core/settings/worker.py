"""Simulation worker settings (docs/27 §4.4).

Layer: Kernel (L1).
"""

import socket

from pydantic import Field

from roboprobe.core.settings._base import PORT_MAX, SettingsSection

__all__ = ["WorkerSettings"]


class WorkerSettings(SettingsSection):
    """Worker process settings. ``backend`` is required by worker processes only."""

    backend: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Simulator backend key (`kinematic2d`, `gazebo_nav2`); required to start a worker."
        ),
    )
    id_prefix: str = Field(
        default_factory=socket.gethostname,
        min_length=1,
        description="Worker id prefix; id = `<prefix>:<pid>:<slot>` (default: host name).",
        json_schema_extra={"doc_default": "<hostname>"},
    )
    concurrency: int = Field(default=1, gt=0, description="Simulation slots per process.")
    poll_interval_s: float = Field(default=1.0, gt=0, description="Queue poll interval [s].")
    heartbeat_interval_s: float = Field(default=5.0, gt=0, description="Heartbeat interval [s].")
    drain_timeout_s: float = Field(
        default=600.0, gt=0, description="Grace period to finish runs on SIGTERM [s]."
    )
    default_wall_timeout_s: float = Field(
        default=300.0, gt=0, description="Default wall-clock limit per run [s]."
    )
    default_sim_time_budget_s: float = Field(
        default=120.0, gt=0, description="Default simulated-time budget per run [s]."
    )
    health_port: int = Field(
        default=9101, ge=1, le=PORT_MAX, description="Internal `/healthz` + metrics port."
    )
