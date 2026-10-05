"""Logging with per-request correlation IDs.

RequestContextMiddleware assigns every request an ID (or adopts an incoming X-Request-ID),
exposes it on the response, adds it to every log line, and logs one access line per request.
"""

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
access_log = logging.getLogger("cellloop.access")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Uvicorn's own access log duplicates ours (without request IDs).
    logging.getLogger("uvicorn.access").disabled = True


def _oversized(request: Request) -> Response | None:
    """Refuse bodies over the upload limit before they are read or spooled to disk."""
    from .config import get_settings
    from .errors import error_body

    limit = (get_settings().max_upload_mb + 1) * 1024 * 1024  # +1 MB for multipart framing
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > limit:
        from starlette.responses import JSONResponse

        return JSONResponse(error_body(413, f"Request too large (limit {get_settings().max_upload_mb} MB).", "payload_too_large"), status_code=413)
    return None


def _security_headers(request: Request, response: Response) -> None:
    from .config import get_settings

    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "no-referrer")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/api/"):
        # API responses carry R&D data: never store them in shared or browser caches.
        h.setdefault("Cache-Control", "no-store")
    if get_settings().app_env == "prod":
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if 8 <= len(incoming) <= 64 and incoming.replace("-", "").isalnum() else uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            try:
                too_big = _oversized(request)
                response = too_big or await call_next(request)
            except Exception:
                # Handle crashes here (not in a global handler) so the request ID is still set.
                from .errors import error_body  # local import: errors imports this module

                logging.getLogger("cellloop.errors").exception("Unhandled error")
                from starlette.responses import JSONResponse

                response = JSONResponse(error_body(500, f"Something went wrong on our side. Reference: {rid}", "internal_error"), status_code=500)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            _security_headers(request, response)
            return response
        finally:
            ms = (time.perf_counter() - start) * 1000
            if request.url.path != "/api/health":
                level = logging.WARNING if status >= 500 else logging.INFO
                access_log.log(level, "%s %s -> %s (%.0f ms)", request.method, request.url.path, status, ms)
            request_id_var.reset(token)
