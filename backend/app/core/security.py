"""Authentication (Amazon Cognito or local dev tokens) and role-based authorization."""

import logging
import time
from functools import lru_cache
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from ..models import INTERNAL_ORG, INTERNAL_ROLES, Role, User

settings = get_settings()
bearer = HTTPBearer(auto_error=False)
log = logging.getLogger(__name__)

# Cognito group name -> role. A user in several groups gets the most privileged.
ROLE_PRIORITY = [Role.admin, Role.scientist, Role.leadership, Role.partner]


# --- Cognito -------------------------------------------------------------------

def _issuer() -> str:
    return f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/{settings.cognito_user_pool_id}"


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{_issuer()}/.well-known/jwks.json", cache_keys=True, lifespan=3600)


def verify_cognito_id_token(token: str) -> dict:
    """Validate signature, issuer, audience, expiry and token_use of a Cognito ID token."""
    signing_key = _jwks_client().get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.cognito_app_client_id,
        issuer=_issuer(),
        options={"require": ["exp", "iat", "sub", "token_use"]},
    )
    if claims.get("token_use") != "id":
        raise jwt.InvalidTokenError("Expected a Cognito ID token")
    return claims


def claims_to_identity(claims: dict) -> tuple[Role, str]:
    groups = set(claims.get("cognito:groups", []))
    role = next((r for r in ROLE_PRIORITY if r.value in groups), None)
    if role is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is not assigned to a CellLoop group")
    if role in INTERNAL_ROLES:
        return role, INTERNAL_ORG
    org = claims.get("custom:organization")
    if not org or org == INTERNAL_ORG:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Partner account has no organization assigned")
    return role, org


# --- Dev tokens ------------------------------------------------------------------

def mint_dev_token(user: User, ttl_s: int = 12 * 3600) -> str:
    if settings.app_env == "prod" or settings.auth_mode != "dev":
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    now = int(time.time())
    return jwt.encode(
        {"sub": user.subject, "email": user.email, "iat": now, "exp": now + ttl_s, "iss": "cellloop-dev"},
        settings.dev_jwt_secret,
        algorithm="HS256",
    )


# --- Dependencies ------------------------------------------------------------------

def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = creds.credentials
    try:
        if settings.auth_mode == "cognito":
            claims = verify_cognito_id_token(token)
            role, org = claims_to_identity(claims)
            user = db.scalar(select(User).where(User.subject == claims["sub"]))
            if user is None:
                user = User(subject=claims["sub"], email=claims.get("email", ""), name=claims.get("name", ""),
                            role=role.value, organization=org)
                db.add(user)
            else:  # Cognito groups are the source of truth; re-sync on every request
                user.role, user.organization = role.value, org
            db.commit()
            return user

        if settings.app_env == "prod":
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Dev auth is disabled in production")
        claims = jwt.decode(token, settings.dev_jwt_secret, algorithms=["HS256"], issuer="cellloop-dev")
        user = db.scalar(select(User).where(User.subject == claims["sub"]))
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
        return user
    except (jwt.PyJWTError, httpx.HTTPError) as exc:
        # Don't echo validation internals to the client; log the reason instead.
        log.info("Rejected token: %s", type(exc).__name__)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session is invalid or has expired. Please sign in again.") from exc


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role):
    allowed = {r.value for r in roles}

    def dep(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role cannot perform this action")
        return user

    return dep


InternalUser = Annotated[User, Depends(require_roles(Role.scientist, Role.leadership, Role.admin))]
Reviewer = Annotated[User, Depends(require_roles(Role.scientist, Role.admin))]
Uploader = Annotated[User, Depends(require_roles(Role.partner, Role.scientist, Role.admin))]
Admin = Annotated[User, Depends(require_roles(Role.admin))]
