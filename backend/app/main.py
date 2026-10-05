"""FastAPI application: middleware, error handling, routers and health check."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .core.config import get_settings
from .core.database import engine, init_db
from .core.errors import install_error_handlers
from .core.logging import RequestContextMiddleware, configure_logging
from .routers import auth, documents, experiments, insights

settings = get_settings()
configure_logging(settings.log_level)
log = logging.getLogger("cellloop")


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info(
        "Starting CellLoop (env=%s, auth=%s, ai=%s, storage=%s, db=%s)",
        settings.app_env, settings.auth_mode, settings.llm_provider, settings.storage_backend,
        "postgres" if settings.is_postgres else "sqlite",
    )
    if settings.llm_provider == "mock":
        log.warning("LLM_PROVIDER=mock: extraction and Q&A use the offline stand-in, not Claude.")
    if settings.auth_mode == "dev" and settings.using_default_dev_secret and settings.app_env != "test":
        log.warning("Using the default DEV_JWT_SECRET. Fine locally; set a random value anywhere shared.")
    try:
        init_db()
    except SQLAlchemyError as exc:
        log.critical("Cannot connect to the database (%s). Check DATABASE_URL in backend/.env.", exc.__class__.__name__)
        raise SystemExit(1) from None
    yield
    log.info("CellLoop stopped")


app = FastAPI(
    title="CellLoop API",
    description="Experiment registry, AI report extraction, Bayesian next-experiment recommender and "
                "cited Q&A for metal-supported SOFC development.",
    version="0.1.0",
    lifespan=lifespan,
    # Interactive docs reveal the full API surface; keep them to dev/test.
    docs_url=None if settings.app_env == "prod" else "/docs",
    redoc_url=None if settings.app_env == "prod" else "/redoc",
    openapi_url=None if settings.app_env == "prod" else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestContextMiddleware)
install_error_handlers(app)

for r in (auth.router, documents.router, experiments.router, insights.router):
    app.include_router(r)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """The API has no UI of its own; send people who open it in a browser to the web app."""
    return RedirectResponse(settings.frontend_url)


@app.get("/api/health", tags=["meta"])
def health() -> JSONResponse:
    """Liveness + readiness: reports 503 if the database can't be reached."""
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        db_ok = False
    body = {
        "status": "ok" if db_ok else "degraded",
        "database": ("postgres" if settings.is_postgres else "sqlite") + ("" if db_ok else " (unreachable)"),
        "llm_provider": settings.llm_provider,
        "storage": settings.storage_backend,
        "version": app.version,
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)
