from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..core import ratelimit
from sqlalchemy import select

from ..core.security import CurrentUser, mint_dev_token
from ..core.config import get_settings
from ..core.database import SessionLocal
from ..experiment_schema import DESIGN_SPACE, FIELD_SPECS, FIELDS_BY_KEY
from ..models import User

router = APIRouter(prefix="/api", tags=["auth"])
settings = get_settings()


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "organization": u.organization,
            "is_internal": u.is_internal}


class DevLogin(BaseModel):
    email: str = Field(max_length=320)


@router.get("/config")
def public_config() -> dict:
    """Unauthenticated: tells the SPA how to log in and describes the experiment schema."""
    return {
        "auth_mode": settings.auth_mode,
        "llm_provider": settings.llm_provider,
        "fields": [f.to_dict() for f in FIELD_SPECS],
        "design_space": [
            {"key": k, "label": FIELDS_BY_KEY[k].label, "unit": FIELDS_BY_KEY[k].unit, "min": lo, "max": hi}
            for k, (lo, hi) in DESIGN_SPACE.items()
        ],
        "targets": {"asr_ohm_cm2": settings.target_asr_ohm_cm2, "operating_temp_c": settings.target_operating_temp_c,
                    "turnaround_hours": settings.turnaround_target_hours},
    }


@router.get("/auth/dev-users")
def dev_users() -> list[dict]:
    if settings.auth_mode != "dev" or settings.app_env == "prod":
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    with SessionLocal() as db:
        return [user_out(u) for u in db.scalars(select(User).order_by(User.role, User.email))]


@router.post("/auth/dev-login")
def dev_login(body: DevLogin, request: Request) -> dict:
    if settings.auth_mode != "dev" or settings.app_env == "prod":
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    ratelimit.check(f"login:{ratelimit.client_ip(request)}", settings.rate_limit_login_per_min)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == body.email.lower()))
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown dev user")
        return {"token": mint_dev_token(user), "user": user_out(user)}


@router.get("/auth/me")
def me(user: CurrentUser) -> dict:
    return user_out(user)
