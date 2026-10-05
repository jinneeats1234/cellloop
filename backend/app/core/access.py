"""Tenant isolation. Every query for partner-owned data goes through these helpers.

Partners see only rows whose `organization` equals their own; internal users see all.
Out-of-scope lookups return 404 (not 403) so partners cannot probe for other labs' IDs.
"""

from typing import TypeVar

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ..models import INTERNAL_ORG, Chunk, Document, Experiment, Role, User

T = TypeVar("T", Document, Experiment, Chunk)


def scope(stmt: Select, model: type[T], user: User) -> Select:
    if user.is_internal:
        return stmt
    return stmt.where(model.organization == user.organization)


def get_scoped(db: Session, model: type[T], obj_id: str, user: User) -> T:
    obj = db.get(model, obj_id)
    if obj is None or (not user.is_internal and obj.organization != user.organization):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} not found")
    return obj


def partner_organizations(db: Session) -> set[str]:
    """Organizations that have at least one partner account: the only valid tenants for partner data."""
    return set(db.scalars(select(User.organization).where(User.role == Role.partner.value).distinct()))


def require_known_org(db: Session, org: str | None, *, allow_internal: bool = False) -> str:
    """Validate an organization chosen by an internal user (it also becomes part of a storage path)."""
    valid = partner_organizations(db) | ({INTERNAL_ORG} if allow_internal else set())
    if not org or org not in valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            {"message": "Unknown organization", "allowed": sorted(valid)})
    return org
