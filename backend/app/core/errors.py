"""Consistent, safe error responses.

Every error the API returns has the same JSON shape:

    {"detail": <str | object>, "code": "not_found", "request_id": "3f9c…"}

`detail` stays FastAPI-compatible (clients and tests read it). `code` is a stable,
machine-readable identifier. `request_id` matches the X-Request-ID response header and
the server log line, so a user-reported error can be traced. Unexpected exceptions are
logged with a stack trace but never leak internals to the client.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging import request_id_var

log = logging.getLogger("cellloop.errors")

STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "upstream_error",
    503: "service_unavailable",
}


class AppError(Exception):
    """Raise for expected failures; the handler turns it into a clean JSON response."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, detail: Any = None, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail if detail is not None else message
        if code:
            self.code = code


class NotFoundError(AppError):
    status_code, code = 404, "not_found"


class ConflictError(AppError):
    status_code, code = 409, "conflict"


class ProcessingError(AppError):
    """The request was valid but the data couldn't be processed (e.g. a model failed to fit)."""

    status_code, code = 422, "processing_failed"


class UpstreamError(AppError):
    """A dependency (Bedrock, S3) failed in a way the user can retry."""

    status_code, code = 502, "upstream_error"


class ServiceUnavailableError(AppError):
    status_code, code = 503, "service_unavailable"


def user_message(exc: BaseException) -> str:
    """A message safe to show users for a failure in background work (no internals)."""
    from ..services.parsing import UnreadableFileError  # local: services import this module

    if isinstance(exc, AppError):
        return exc.message
    if isinstance(exc, UnreadableFileError):
        return str(exc)
    return "Processing failed because of an unexpected error. The team can trace it in the server logs."


def error_body(status: int, detail: Any, code: str | None = None) -> dict[str, Any]:
    return {"detail": detail, "code": code or STATUS_CODES.get(status, "error"), "request_id": request_id_var.get()}


def _friendly_validation(errors: list[dict[str, Any]]) -> str:
    parts = []
    for e in errors[:5]:
        loc = [str(p) for p in e.get("loc", ()) if p not in ("body", "query", "path", "form")]
        field = ".".join(loc) or "request"
        parts.append(f"{field}: {e.get('msg', 'invalid value')}")
    more = f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""
    return "Invalid input — " + "; ".join(parts) + more


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            log.warning("%s: %s", exc.code, exc.message)
        return JSONResponse(error_body(exc.status_code, exc.detail, exc.code), status_code=exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        code = detail.get("code") if isinstance(detail, dict) and isinstance(detail.get("code"), str) else None
        return JSONResponse(error_body(exc.status_code, detail, code), status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        body = error_body(422, errors, "validation_error")
        body["message"] = _friendly_validation(errors)
        # Pydantic error objects can hold non-JSON values (e.g. the exception in ctx); stringify them.
        for e in body["detail"]:
            if "ctx" in e:
                e["ctx"] = {k: str(v) for k, v in e["ctx"].items()}
            e.pop("input", None)  # don't echo user input (could be large or sensitive)
        return JSONResponse(body, status_code=422)

    @app.exception_handler(OperationalError)
    async def _db_unavailable(_: Request, exc: OperationalError) -> JSONResponse:
        log.error("Database unavailable: %s", exc.orig)
        return JSONResponse(error_body(503, "The database is temporarily unavailable. Please try again shortly.", "database_unavailable"), status_code=503)

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        log.exception("Database error")
        return JSONResponse(error_body(500, "A database error occurred. The team has been notified.", "database_error"), status_code=500)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error")
        rid = request_id_var.get()
        return JSONResponse(error_body(500, f"Something went wrong on our side. Reference: {rid}", "internal_error"), status_code=500)
