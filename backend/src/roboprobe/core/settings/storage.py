"""Artifact and scratch storage settings (docs/27 §4.2).

Layer: Kernel (L1).
"""

from pathlib import Path

from pydantic import Field

from roboprobe.core.settings._base import SettingsSection

__all__ = ["BundleSettings", "RetentionSettings", "StorageSettings"]

_DEFAULT_MAX_UNCOMPRESSED = 2_147_483_648
_DEFAULT_MAX_MEMBER = 536_870_912
_DEFAULT_CHUNK = 1_048_576
_HOSTNAME_HASH_HEX = 16


class RetentionSettings(SettingsSection):
    """Retention policy for large run artefacts."""

    bags_days: int = Field(default=30, gt=0, description="Days to keep rosbag artefacts [d].")
    keep_failure_bags: bool = Field(
        default=True, description="Keep bags of failing runs regardless of `bags_days`."
    )


class BundleSettings(SettingsSection):
    """Campaign ``.tar.zst`` export/import limits (T-014, TM-14)."""

    format_version: int = Field(
        default=1, ge=1, description="Campaign bundle format version written on export."
    )
    max_uncompressed_bytes: int = Field(
        default=_DEFAULT_MAX_UNCOMPRESSED,
        gt=0,
        description="Maximum total uncompressed payload accepted on import [bytes].",
    )
    max_member_bytes: int = Field(
        default=_DEFAULT_MAX_MEMBER,
        gt=0,
        description="Maximum size of any single tar member on import [bytes].",
    )
    read_chunk_bytes: int = Field(
        default=_DEFAULT_CHUNK,
        gt=0,
        description="I/O chunk size when hashing or copying bundle members [bytes].",
    )
    hostname_hash_hex: int = Field(
        default=_HOSTNAME_HASH_HEX,
        gt=0,
        le=64,
        description="Hex length of hostname hashes written into exported manifests (TM-15).",
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
    bundle: BundleSettings = Field(default_factory=BundleSettings)
    backend: str = Field(
        default="local",
        min_length=1,
        description="Artifact store plugin key in the `roboprobe.stores` entry-point group.",
    )
