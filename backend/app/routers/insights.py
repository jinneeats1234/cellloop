"""Recommender, cited Q&A, program dashboard and audit log (internal users only)."""

import statistics
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import audit, ratelimit
from ..core.validation import Text
from ..core.security import InternalUser
from ..core.config import get_settings
from ..core.database import get_db
from ..experiment_schema import FIELDS_BY_KEY, REQUIRED_KEYS
from ..models import AuditLog, Document, Experiment, ExperimentStatus
from ..services import rag
from ..services.recommender import recommend

router = APIRouter(prefix="/api", tags=["insights"])
settings = get_settings()
DB = Annotated[Session, Depends(get_db)]


class RecommendBody(BaseModel):
    n: int = Field(5, ge=1, le=12)
    target_temp_c: float | None = Field(None, ge=400, le=1000)
    temp_tolerance_c: float = Field(25.0, ge=0, le=200)
    target_asr: float | None = Field(None, ge=0.01, le=50)
    filters: dict[str, Annotated[str, Field(max_length=100)]] = Field(default_factory=dict)  # e.g. {"cathode_composition": "LSCF"}


ALLOWED_FILTERS = {"support_alloy", "anode_composition", "electrolyte_composition", "cathode_composition",
                   "coating_material"}


@router.post("/recommendations")
def recommendations(body: RecommendBody, db: DB, user: InternalUser) -> dict:
    ratelimit.check(f"ai:{user.id}", settings.rate_limit_ai_per_min)
    filters = {k: v.strip() for k, v in body.filters.items() if k in ALLOWED_FILTERS and v and v.strip()}
    if any("\x00" in v for v in filters.values()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Filter contains an invalid character")
    result = recommend(db, n=body.n, target_temp_c=body.target_temp_c, temp_tolerance_c=body.temp_tolerance_c,
                       target_asr=body.target_asr, filters=filters)
    audit.record(db, actor=user, action="recommend", entity_type="recommendation", entity_id=None,
                 organization=None, details={"request": body.model_dump(), "engine": result["engine"],
                                             "n_training": result["n_training"],
                                             "top": result["candidates"][0]["params"] if result["candidates"] else None})
    db.commit()
    return result


class Question(BaseModel):
    question: Text("Question", 3, 2000)


@router.post("/qa")
def ask(body: Question, db: DB, user: InternalUser) -> dict:
    ratelimit.check(f"ai:{user.id}", settings.rate_limit_ai_per_min)
    result = rag.answer_question(db, user, body.question)
    audit.record(db, actor=user, action="qa_query", entity_type="qa", entity_id=None, organization=None,
                 details={"question": body.question, "answered": result["answered"], "reason": result["reason"],
                          "cited": [c["label"] for c in result["citations"]]})
    db.commit()
    return result


def _as_date(e: Experiment) -> date:
    if e.test_date:
        return e.test_date
    ts = e.reviewed_at or e.submitted_at
    return ts.date() if isinstance(ts, datetime) else date.today()


def _hours(a: datetime, b: datetime) -> float:
    if (a.tzinfo is None) != (b.tzinfo is None):  # SQLite drops tzinfo; normalise
        a, b = a.replace(tzinfo=None), b.replace(tzinfo=None)
    return (a - b).total_seconds() / 3600


@router.get("/dashboard")
def dashboard(db: DB, user: InternalUser) -> dict:
    exps = list(db.scalars(select(Experiment)))
    approved = [e for e in exps if e.status == ExperimentStatus.approved.value]
    counts = {s.value: sum(1 for e in exps if e.status == s.value) for s in ExperimentStatus}

    # Turnaround: partner submission -> approved structured record.
    turnaround = [_hours(e.reviewed_at, e.submitted_at) for e in approved
                  if e.source == "extracted" and e.reviewed_at and e.submitted_at]
    within = sum(1 for h in turnaround if h <= settings.turnaround_target_hours)

    # Metadata completeness.
    complete = sum(1 for e in approved if (e.completeness or 0) >= 0.999)
    missing_rate = []
    for key in REQUIRED_KEYS:
        n_missing = sum(1 for e in approved if getattr(e, key) in (None, ""))
        missing_rate.append({"key": key, "label": FIELDS_BY_KEY[key].label,
                             "missing_pct": round(100 * n_missing / len(approved), 1) if approved else 0})
    missing_rate.sort(key=lambda r: -r["missing_pct"])

    # Progress toward the ASR target at the target operating temperature.
    t0 = settings.target_operating_temp_c
    at_temp = sorted((e for e in approved if e.asr_ohm_cm2 and e.operating_temp_c is not None
                      and abs(e.operating_temp_c - t0) <= 25), key=lambda e: (_as_date(e), e.code))
    progress, best = [], None
    cycles_to_target = None
    for i, e in enumerate(at_temp, start=1):
        best = e.asr_ohm_cm2 if best is None else min(best, e.asr_ohm_cm2)
        progress.append({"cycle": i, "date": _as_date(e).isoformat(), "code": e.code, "id": e.id,
                         "asr": e.asr_ohm_cm2, "best": best, "organization": e.organization})
        if cycles_to_target is None and e.asr_ohm_cm2 <= settings.target_asr_ohm_cm2:
            cycles_to_target = i

    by_partner: dict[str, dict[str, int]] = {}
    for e in exps:
        row = by_partner.setdefault(e.organization, {s.value: 0 for s in ExperimentStatus})
        row[e.status] += 1

    recent = db.scalars(select(AuditLog).order_by(AuditLog.at.desc()).limit(12))
    return {
        "targets": {"asr_ohm_cm2": settings.target_asr_ohm_cm2, "operating_temp_c": t0,
                    "turnaround_hours": settings.turnaround_target_hours,
                    "completeness_pct": 90, "cycle_reduction_pct": 25,
                    "baseline_cycles_to_target": settings.baseline_cycles_to_target},
        "counts": {**counts, "total": len(exps),
                   "documents": db.scalar(select(func.count()).select_from(Document)) or 0,
                   "partners": len({e.organization for e in exps if e.organization != "internal"})},
        "turnaround": {
            "median_hours": round(statistics.median(turnaround), 1) if turnaround else None,
            "pct_within_target": round(100 * within / len(turnaround), 1) if turnaround else None,
            "n": len(turnaround),
        },
        "completeness": {"pct_complete": round(100 * complete / len(approved), 1) if approved else None,
                         "n": len(approved), "missing_by_field": missing_rate},
        "progress": {
            "series": progress,
            "best_asr": best,
            "cycles_to_target": cycles_to_target,
            "cycle_reduction_pct": round(100 * (1 - cycles_to_target / settings.baseline_cycles_to_target), 1)
            if cycles_to_target else None,
        },
        "asr_vs_temp": [{"code": e.code, "id": e.id, "temp": e.operating_temp_c, "asr": e.asr_ohm_cm2,
                         "cathode": e.cathode_composition, "organization": e.organization}
                        for e in approved if e.asr_ohm_cm2 and e.operating_temp_c],
        "by_partner": by_partner,
        "recent_activity": [{"at": a.at.isoformat(), "actor": a.actor_email, "action": a.action,
                             "entity_type": a.entity_type, "entity_id": a.entity_id} for a in recent],
    }


@router.get("/audit")
def audit_log(db: DB, user: InternalUser, entity_id: str | None = None, action: str | None = None,
              limit: Annotated[int, Query(ge=1, le=1000)] = 200, offset: Annotated[int, Query(ge=0)] = 0) -> list[dict]:
    stmt = select(AuditLog).order_by(AuditLog.at.desc(), AuditLog.id.desc())
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return [{"id": a.id, "at": a.at.isoformat(), "actor": a.actor_email, "action": a.action,
             "entity_type": a.entity_type, "entity_id": a.entity_id, "organization": a.organization,
             "details": a.details} for a in db.scalars(stmt.limit(limit).offset(offset))]
