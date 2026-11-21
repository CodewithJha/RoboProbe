"""RFC 9457 ``application/problem+json`` error handlers (docs/12 §1.1).

Implements: T-080b, FR-API-003
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from roboprobe.core.errors import (
    API_ERROR_CODES,
    ConflictError,
    ErrorCode,
    NotFoundError,
    RoboProbeError,
    ValidationError,
)

__all__ = [
    "ERROR_MAP",
    "FieldError",
    "ProblemDetail",
    "install_error_handlers",
    "problem_response",
    "problem_type_url",
]

_STATUS: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CAMPAIGN_INVALID_TRANSITION: 409,
    ErrorCode.SPACE_INVALID: 422,
    ErrorCode.BACKEND_UNSUPPORTED_PARAM: 422,
    ErrorCode.NO_WORKERS: 409,
    ErrorCode.PRECONDITION_FAILED: 412,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.INTERNAL: 500,
}

_TITLES: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION_ERROR: "Validation error",
    ErrorCode.NOT_FOUND: "Not found",
    ErrorCode.CAMPAIGN_INVALID_TRANSITION: "Invalid state transition",
    ErrorCode.SPACE_INVALID: "Invalid scenario space",
    ErrorCode.BACKEND_UNSUPPORTED_PARAM: "Backend unsupported parameter",
    ErrorCode.NO_WORKERS: "No workers available",
    ErrorCode.PRECONDITION_FAILED: "Precondition failed",
    ErrorCode.UNAUTHORIZED: "Unauthorized",
    ErrorCode.INTERNAL: "Internal server error",
}

ERROR_MAP: dict[type[RoboProbeError], tuple[int, ErrorCode]] = {
    ValidationError: (422, ErrorCode.VALIDATION_ERROR),
    NotFoundError: (404, ErrorCode.NOT_FOUND),
    ConflictError: (409, ErrorCode.CONFLICT),
}


class FieldError(BaseModel):
    """One field-level validation problem (RFC 6901 pointer)."""

    model_config = ConfigDict(extra="forbid")

    pointer: str
    detail: str


class ProblemDetail(BaseModel):
    """RFC 9457 problem document plus RoboProbe ``code`` / ``errors``."""

    model_config = ConfigDict(extra="forbid")

    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    errors: list[FieldError] = Field(default_factory=list)
    trace_id: str | None = None


def problem_type_url(base: str, code: ErrorCode | str) -> str:
    """Build the ``type`` URL with a docs/errors.md-style anchor."""
    slug = str(code).lower().replace("_", "-")
    return f"{base.rstrip('/')}#{slug}"


def problem_response(  # noqa: PLR0913 - RFC 9457 fields are independent
    *,
    request: Request,
    code: ErrorCode,
    detail: str,
    status: int | None = None,
    errors: list[FieldError] | None = None,
    title: str | None = None,
    trace_id: str | None = None,
) -> JSONResponse:
    """Return a ``application/problem+json`` response for ``code``."""
    settings = request.app.state.settings
    http_status = status if status is not None else _STATUS[code]
    body = ProblemDetail(
        type=problem_type_url(settings.api.error_type_base, code),
        title=title or _TITLES[code],
        status=http_status,
        detail=detail,
        instance=str(request.url.path),
        code=code.value,
        errors=errors or [],
        trace_id=trace_id,
    )
    return JSONResponse(
        status_code=http_status,
        content=body.model_dump(exclude_none=True),
        media_type="application/problem+json",
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register RoboProbe and FastAPI validation handlers on ``app``."""

    @app.exception_handler(RoboProbeError)
    async def _roboprobe_error(request: Request, exc: RoboProbeError) -> JSONResponse:
        code = exc.code if exc.code in API_ERROR_CODES else _fallback_code(exc)
        status = _STATUS.get(code, 500)
        if code is ErrorCode.INTERNAL:
            return _internal(request)
        return problem_response(request=request, code=code, detail=exc.message, status=status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [_field_error(err) for err in exc.errors()]
        return problem_response(
            request=request,
            code=ErrorCode.VALIDATION_ERROR,
            detail="Request validation failed",
            errors=errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 401:
            code = ErrorCode.UNAUTHORIZED
        elif exc.status_code == 404:
            code = ErrorCode.NOT_FOUND
        elif exc.status_code == 412:
            code = ErrorCode.PRECONDITION_FAILED
        elif exc.status_code == 415:
            code = ErrorCode.VALIDATION_ERROR
        else:
            code = ErrorCode.INTERNAL if exc.status_code >= 500 else ErrorCode.VALIDATION_ERROR
        detail = str(exc.detail)
        if code is ErrorCode.INTERNAL:
            return _internal(request)
        return problem_response(request=request, code=code, detail=detail, status=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        del exc
        structlog.get_logger("api").exception("api.unhandled")
        return _internal(request)


def _fallback_code(exc: RoboProbeError) -> ErrorCode:
    if isinstance(exc, NotFoundError):
        return ErrorCode.NOT_FOUND
    if isinstance(exc, ValidationError):
        return ErrorCode.VALIDATION_ERROR
    if isinstance(exc, ConflictError):
        if exc.code in API_ERROR_CODES:
            return exc.code
        return ErrorCode.CAMPAIGN_INVALID_TRANSITION
    return ErrorCode.INTERNAL


def _field_error(err: dict[str, Any]) -> FieldError:
    loc = err.get("loc", ())
    parts = [str(part) for part in loc if part not in {"body", "query", "path", "header"}]
    pointer = "/" + "/".join(parts) if parts else "/"
    return FieldError(pointer=pointer, detail=str(err.get("msg", "invalid")))


def _internal(request: Request) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None)
    return problem_response(
        request=request,
        code=ErrorCode.INTERNAL,
        detail="An internal error occurred",
        trace_id=trace_id if isinstance(trace_id, str) else None,
    )
