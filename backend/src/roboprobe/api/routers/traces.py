"""Trace JSON and Parquet transport (T-081e, FR-DSH-005)."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from roboprobe.api.deps import get_services, get_uow
from roboprobe.api.downloads import artifact_path, download_response
from roboprobe.api.downsample import sample_indices
from roboprobe.api.schemas import TraceOut
from roboprobe.core.errors import NotFoundError, ValidationError

__all__ = ["router"]
router = APIRouter(tags=["runs"])
_PARQUET = "application/vnd.apache.parquet"


@router.get(
    "/runs/{run_id}/trace",
    response_model=TraceOut,
    responses={200: {"content": {_PARQUET: {"schema": {"type": "string", "format": "binary"}}}}},
)
def get_trace(
    run_id: UUID,
    request: Request,
    hz: Annotated[float | None, Query(gt=0, allow_inf_nan=False)] = None,
    columns: str | None = None,
    uow: Any = Depends(get_uow),
) -> dict[str, Any] | FileResponse:
    """Return event-preserving JSON columns or stream the original Parquet file."""
    run = uow.runs.get(run_id)
    if run is None:
        msg = "run not found"
        raise NotFoundError(msg)
    artifact = next(
        (row for row in uow.artifacts.list_for_run(run_id) if row.kind == "trace"), None
    )
    if artifact is None:
        msg = "run trace not found"
        raise NotFoundError(msg)
    services = get_services(request)
    path = artifact_path(services.artifact_store, artifact)
    if _PARQUET in request.headers.get("accept", ""):
        return download_response(path, artifact, ordinal=run.ordinal)
    requested_hz = services.settings.api.trace_default_hz if hz is None else hz
    effective_hz = min(requested_hz, services.settings.api.trace_max_hz)
    try:
        table = pq.read_table(path)
    except (pa.ArrowException, OSError) as exc:
        msg = "stored trace is not valid Parquet"
        raise ValidationError(msg) from exc
    names = table.column_names
    requested = (
        names
        if columns is None
        else list(dict.fromkeys(part.strip() for part in columns.split(",")))
    )
    if set(requested) - set(names) or not {"t", "min_obstacle_dist"} <= set(names):
        msg = "unknown trace columns or missing required trace columns"
        raise ValidationError(msg)
    t = np.asarray(table["t"].to_numpy(), dtype=np.float64)
    clearance = np.asarray(table["min_obstacle_dist"].to_numpy(), dtype=np.float64)
    flags = {
        name: np.asarray(table[name].to_numpy())
        for name in names
        if pa.types.is_boolean(table.schema.field(name).type) or name == "nav_status"
    }
    indices = sample_indices(t, clearance, flags, hz=effective_hz)
    selected = table.take(indices)
    source_hz = float(1 / np.median(np.diff(t))) if len(t) > 1 else None
    return {
        "t": selected["t"].to_pylist(),
        "columns": {name: selected[name].to_pylist() for name in requested if name != "t"},
        "hz": effective_hz,
        "source_hz": source_hz,
        "truncated": len(indices) < len(t) or effective_hz < requested_hz,
    }
