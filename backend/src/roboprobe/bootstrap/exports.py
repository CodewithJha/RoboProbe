"""Campaign bundle export composition (T-082c, FR-STO-003)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from roboprobe.core.settings import RoboProbeSettings
from roboprobe.store.bundle import export_campaign

__all__ = ["bundle_work"]


def bundle_work(
    campaign_id: UUID,
    *,
    uow_factory: Callable[[], object],
    artifact_store: object,
    settings: RoboProbeSettings,
) -> Callable[[], Path]:
    """Build an export worker using the same bundle service as the CLI."""

    def work() -> Path:
        output = settings.storage.workdir_root / "exports" / f"{campaign_id}-{uuid4()}.tar.zst"
        with cast("Any", uow_factory()) as uow:
            return export_campaign(
                campaign_id,
                uow,
                cast("Any", artifact_store),
                output,
                settings=settings.storage.bundle,
            )

    return work
