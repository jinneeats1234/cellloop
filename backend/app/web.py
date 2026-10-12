"""Serve the built React app (frontend/dist) from the API process.

Used for single-service deployments (Docker on Render, etc.): one URL serves the web app
and /api, so no proxy or CORS setup is needed. Enabled when STATIC_DIR points at a build.
Local development keeps the separate Vite dev server.
"""

import logging
import mimetypes
import stat
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.types import Scope

log = logging.getLogger("cellloop.web")

# Mirrors frontend/security-headers.js (the policy the Node server and nginx send).
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self' https://*.amazoncognito.com",
    "frame-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self' https://*.amazoncognito.com",
    "frame-ancestors 'none'",
])


IMMUTABLE = "public, max-age=31536000, immutable"


class ImmutableStaticFiles(StaticFiles):
    """Vite fingerprints every file in /assets, so browsers may cache them for a year.

    If a pre-compressed `<file>.gz` exists (the Dockerfile creates them at build time), it is
    sent to browsers that accept gzip: a 4.7 MB charting bundle goes out as ~1.4 MB with no
    per-request CPU cost, which matters on small instances.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        if "gzip" in Headers(scope=scope).get("accept-encoding", ""):
            full_path, stat_result = self.lookup_path(path + ".gz")
            if stat_result is not None and stat.S_ISREG(stat_result.st_mode):
                media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
                return FileResponse(full_path, media_type=media_type, stat_result=stat_result, headers={
                    "Content-Encoding": "gzip", "Vary": "Accept-Encoding", "Cache-Control": IMMUTABLE})
        return await super().get_response(path, scope)

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = IMMUTABLE
        response.headers["Vary"] = "Accept-Encoding"
        return response


def install_static_site(app: FastAPI, dist_dir: Path) -> bool:
    """Register the web app routes. Call AFTER all API routes. Returns False if no build exists."""
    dist = dist_dir.resolve()
    index = dist / "index.html"
    if not index.is_file():
        log.warning("STATIC_DIR=%s has no index.html; the web app won't be served (run npm run build).", dist)
        return False

    if (dist / "assets").is_dir():
        app.mount("/assets", ImmutableStaticFiles(directory=dist / "assets"), name="assets")

    def app_shell() -> FileResponse:
        return FileResponse(index, headers={"Cache-Control": "no-cache", "Content-Security-Policy": CONTENT_SECURITY_POLICY})

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def web_app(full_path: str, request: Request) -> Response:
        # Unknown API paths are real JSON 404s, never the HTML app shell.
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found", "code": "not_found"}, status_code=404)
        if full_path:
            candidate = (dist / full_path).resolve()
            if candidate.is_relative_to(dist) and candidate.is_file():
                return FileResponse(candidate, headers={"Cache-Control": "public, max-age=3600"})
            # A missing file with an extension (an old asset, /favicon.png…) is a 404, not the app.
            if Path(full_path).suffix:
                return PlainTextResponse("Not Found", status_code=404)
        # "/" and client-side routes (/dashboard, /experiments/<id>…) get the app shell.
        return app_shell()

    log.info("Serving the web app from %s", dist)
    return True
