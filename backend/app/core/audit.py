from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog, User

AI_ACTOR = "ai:claude-extraction"


def _jsonable(v: Any) -> Any:
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def record(
    db: Session,
    *,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    organization: str | None,
    details: dict[str, Any] | None = None,
    actor_label: str | None = None,
) -> None:
    """Add an audit entry to the current transaction (committed with the change it describes)."""
    db.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            actor_email=actor.email if actor else (actor_label or "system"),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            organization=organization,
            details={k: _jsonable(v) for k, v in (details or {}).items()},
        )
    )


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        k: {"from": _jsonable(before.get(k)), "to": _jsonable(after.get(k))}
        for k in after
        if _jsonable(before.get(k)) != _jsonable(after.get(k))
    }
