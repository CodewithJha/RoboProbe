"""Artifact and scratch storage settings (docs/27 §4.2).

Layer: Kernel (L1).
"""

from pathlib import Path

from pydantic import Field

from roboprobe.core.settings._base import SettingsSection

__all__ = ["RetentionSettings", "StorageSettings"]


class RetentionSettings(SettingsSection):
    """Retention policy for large run artefacts."""

    bags_days: int = Field(default=30, gt=0, description="Days to keep rosbag artefacts [d].")
    keep_failure_bags: bool = Field(
        default=True, description="Keep bags of failing runs regardless of `bags_days`."
    )


class StorageSettings(SettingsSection):
    """Where artefacts and per-run scratch directories live."""

    artifact_root: Path = Field(
        default=Path("./data/artifacts"), description="Root directory of run artefacts [path]."
    )
    workdir_root: Path = Field(
        default=Path("./data/workdirs"), description="Root of per-run scratch directories [path]."
    )
    min_free_gb: float = Field(
        default=5.0, ge=0, description="Free-space floor that raises `DISK_LOW` [GB]."
    )
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    backend: str = Field(
        default="local",
        min_length=1,
        description="Artifact store plugin key in the `roboprobe.stores` entry-point group.",
    )
