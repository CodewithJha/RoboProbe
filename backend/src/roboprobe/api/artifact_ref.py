"""Artifact open ref without importing ``roboprobe.store``."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

__all__ = ["artifact_ref_from_record"]


def artifact_ref_from_record(record: Any) -> SimpleNamespace:
    """Build a minimal ref object for ``ArtifactStore.open``."""
    return SimpleNamespace(
        id=record.id,
        sha256=record.sha256,
        rel_path=record.rel_path,
        kind=record.kind,
        size_bytes=record.size_bytes,
        media_type=record.media_type,
        run_id=record.run_id,
        campaign_id=record.campaign_id,
    )
