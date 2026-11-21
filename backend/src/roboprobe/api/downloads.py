"""Confined streamed artifact transport (T-081e, FR-STO-002, TM-04)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import structlog
from fastapi.responses import FileResponse

from roboprobe.api.artifact_ref import artifact_ref_from_record
from roboprobe.api.deps import ArtifactStoreProto
from roboprobe.core.errors import NotFoundError, ValidationError

__all__ = ["artifact_path", "download_response"]
log = structlog.get_logger(__name__)


def artifact_path(store: ArtifactStoreProto, artifact: Any) -> Path:
    """Resolve through the store's confinement boundary; conceal unsafe or missing paths."""
    try:
        path = store.path(artifact_ref_from_record(artifact))
        if not path.is_file():
            raise FileNotFoundError
    except (ValidationError, OSError) as exc:
        log.warning("artifact.path_rejected", artifact_id=str(artifact.id))
        msg = "artifact content not found"
        raise NotFoundError(msg, context={"artifact_id": str(artifact.id)}) from exc
    return path


def download_response(path: Path, artifact: Any, *, ordinal: int | None) -> FileResponse:
    """Stream a resolved artifact with safe attachment metadata and a content digest ETag."""
    kind = re.sub(r"[^a-zA-Z0-9_-]", "_", str(artifact.kind))
    suffix = re.sub(r"[^a-zA-Z0-9.]", "", "".join(path.suffixes))
    prefix = str(ordinal) if ordinal is not None else str(artifact.id)
    return FileResponse(
        path,
        media_type=artifact.media_type,
        filename=f"{prefix}-{kind}{suffix}",
        headers={"ETag": f'"{artifact.sha256}"', "X-Content-Type-Options": "nosniff"},
    )
