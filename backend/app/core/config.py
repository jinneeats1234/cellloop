"""Application settings, loaded from environment variables and backend/.env.

Every variable is documented in backend/.env.example. Settings are validated once at
startup: a misconfiguration stops the server with a readable list of problems instead
of failing later on the first request that needs the missing value.
"""

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
# CELLLOOP_ENV_FILE overrides the location; set it to "" to ignore .env entirely (tests do).
_env_override = os.environ.get("CELLLOOP_ENV_FILE")
ENV_FILE: Path | None = (Path(_env_override) if _env_override else None) if _env_override is not None else BACKEND_DIR / ".env"
DEFAULT_DEV_SECRET = "dev-only-secret-change-me-0123456789"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # --- Application --------------------------------------------------------------------
    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    frontend_url: str = "http://localhost:5173"  # where GET / on the API redirects to
    rate_limit_enabled: bool = True
    rate_limit_ai_per_min: int = Field(20, ge=1)       # Q&A + recommendations, per user
    rate_limit_upload_per_min: int = Field(30, ge=1)   # uploads, per user
    rate_limit_login_per_min: int = Field(20, ge=1)    # dev sign-ins, per IP

    # --- Database -----------------------------------------------------------------------
    # Postgres + pgvector in every deployed environment. SQLite is supported for
    # zero-dependency local development and tests (embeddings stored as JSON).
    database_url: str = "sqlite:///./cellloop.db"
    embedding_dim: int = Field(1024, ge=64, le=4096)

    # --- Authentication -----------------------------------------------------------------
    # "cognito": verify Amazon Cognito ID tokens (RS256 via JWKS).
    # "dev": HS256 tokens minted by /api/auth/dev-login for local work. Refused when app_env=prod.
    auth_mode: Literal["dev", "cognito"] = "dev"
    dev_jwt_secret: str = Field(DEFAULT_DEV_SECRET, min_length=32)
    cognito_region: str = "us-east-1"
    cognito_user_pool_id: str = ""
    cognito_app_client_id: str = ""

    # --- File storage -------------------------------------------------------------------
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_dir: str = "./data/uploads"
    s3_bucket: str = ""
    s3_kms_key_id: str = ""
    max_upload_mb: int = Field(25, ge=1, le=500)

    # --- AI -----------------------------------------------------------------------------
    # "bedrock": Claude through Amazon Bedrock + Titan embeddings (data stays in the AWS account).
    # "mock": deterministic offline stand-ins so the app runs without AWS credentials.
    llm_provider: Literal["mock", "bedrock"] = "mock"
    aws_region: str = "us-east-1"
    bedrock_claude_model: str = "anthropic.claude-opus-5-5"
    bedrock_embedding_model: str = "amazon.titan-embed-text-v2:0"
    llm_timeout_s: float = Field(300.0, gt=0, le=3600)
    llm_max_retries: int = Field(2, ge=0, le=10)
    qa_top_k: int = Field(6, ge=1, le=50)
    # Minimum cosine similarity for a passage to count as evidence. Defaults depend on the
    # embedding model: Titan v2 vs. the offline hashed bag-of-words embeddings.
    qa_min_similarity: float | None = Field(None, ge=0, le=1)

    # --- Program targets ----------------------------------------------------------------
    target_asr_ohm_cm2: float = Field(0.30, gt=0)
    target_operating_temp_c: float = Field(650.0, ge=400, le=1000)
    baseline_cycles_to_target: int = Field(40, ge=1)  # cycles-to-target the 25% reduction is measured against
    turnaround_target_hours: float = Field(48.0, gt=0)

    @model_validator(mode="after")
    def _check_combinations(self) -> "Settings":
        problems = []
        if self.auth_mode == "cognito" and not (self.cognito_user_pool_id and self.cognito_app_client_id):
            problems.append("AUTH_MODE=cognito requires COGNITO_USER_POOL_ID and COGNITO_APP_CLIENT_ID")
        if self.storage_backend == "s3" and not self.s3_bucket:
            problems.append("STORAGE_BACKEND=s3 requires S3_BUCKET")
        if not (self.database_url.startswith("postgresql") or self.database_url.startswith("sqlite")):
            problems.append("DATABASE_URL must start with postgresql+psycopg:// or sqlite:///")
        if self.app_env == "prod":
            if self.auth_mode == "dev":
                problems.append("AUTH_MODE=dev is not allowed when APP_ENV=prod (use cognito)")
            if self.database_url.startswith("sqlite"):
                problems.append("APP_ENV=prod requires a PostgreSQL DATABASE_URL")
            if self.storage_backend == "local":
                problems.append("APP_ENV=prod requires STORAGE_BACKEND=s3")
            if any(o == "*" for o in self.cors_origins):
                problems.append("CORS_ORIGINS must list explicit origins in prod, not '*'")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    # --- Derived values -----------------------------------------------------------------
    @property
    def resolved_database_url(self) -> str:
        """SQLite paths are relative to backend/, whatever directory the server starts in."""
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix) and not self.database_url.startswith(prefix + "/"):
            rel = self.database_url[len(prefix):]
            return prefix + str((BACKEND_DIR / rel).resolve())
        return self.database_url

    @property
    def resolved_storage_dir(self) -> Path:
        p = Path(self.local_storage_dir)
        return p if p.is_absolute() else (BACKEND_DIR / p).resolve()

    @property
    def min_similarity(self) -> float:
        if self.qa_min_similarity is not None:
            return self.qa_min_similarity
        return 0.30 if self.llm_provider == "bedrock" else 0.08

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def using_default_dev_secret(self) -> bool:
        return self.dev_jwt_secret == DEFAULT_DEV_SECRET


def _format_errors(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]).upper()
        msg = err["msg"].removeprefix("Value error, ")
        lines.append(f"  • {field + ': ' if field else ''}{msg}")
    return "\n".join(lines)


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        source = f"environment variables / {ENV_FILE}" if ENV_FILE and ENV_FILE.exists() else "environment variables"
        sys.stderr.write(
            f"\nCellLoop configuration error ({source}):\n{_format_errors(exc)}\n"
            f"\nSee backend/.env.example for every setting and its allowed values.\n\n"
        )
        raise SystemExit(2) from None
