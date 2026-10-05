from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core import audit
from ..core.access import get_scoped, require_known_org, scope
from ..core.validation import Text, clean_query, like_contains
from ..core.security import CurrentUser, InternalUser, Reviewer
from ..core.database import get_db
from ..experiment_schema import DESIGN_SPACE, FIELDS_BY_KEY, coerce_value, completeness
from ..models import Chunk, Document, DocumentStatus, Experiment, ExperimentStatus
from ..serializers import experiment_out
from ..services import rag
from ..services.extraction import next_experiment_code
from ..services.recommender import similar_experiments

router = APIRouter(prefix="/api/experiments", tags=["experiments"])
DB = Annotated[Session, Depends(get_db)]

TEXT_SEARCH_FIELDS = ("cell_id", "lab_name", "support_alloy", "anode_composition", "electrolyte_composition",
                      "cathode_composition", "coating_material", "sintering_atmosphere", "notes")


class FieldValues(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict, max_length=100)


class ApproveBody(FieldValues):
    comment: Text("Comment", 0, 2000) | None = None
    acknowledge_warnings: bool = False


class RejectBody(BaseModel):
    reason: Text("Reason", 3, 2000)


class ManualCreate(FieldValues):
    organization: str = Field(max_length=64)
    document_id: str | None = Field(None, max_length=36)


def _coerce_all(values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    unknown = set(values) - set(FIELDS_BY_KEY)
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown fields: {sorted(unknown)}")
    out, problems = {}, {}
    for key, raw in values.items():
        v, problem = coerce_value(FIELDS_BY_KEY[key], raw)
        if problem and v is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"field": key, "message": problem})
        out[key] = v
        if problem:
            problems[key] = problem
    return out, problems


def _apply(exp: Experiment, values: dict[str, Any]) -> dict[str, Any]:
    before = exp.field_values()
    for k, v in values.items():
        setattr(exp, k, v)
    after = exp.field_values()
    exp.completeness, _ = completeness(after)
    return audit.diff(before, {k: after[k] for k in values})


def _pending(exp: Experiment) -> None:
    if exp.status != ExperimentStatus.pending_review.value:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Experiment is {exp.status}; only pending records can change")


@router.get("")
def list_experiments(
    db: DB, user: CurrentUser,
    status_: Annotated[str | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    organization: str | None = None,
    min_temp: float | None = None, max_temp: float | None = None,
    max_asr: float | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500, offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    stmt = scope(select(Experiment), Experiment, user)
    if status_:
        stmt = stmt.where(Experiment.status == status_)
    if organization and user.is_internal:
        stmt = stmt.where(Experiment.organization == organization)
    q = clean_query(q)
    if q:
        # Parameterised by SQLAlchemy (no SQL injection); % and _ are escaped so they match literally.
        like = like_contains(q)
        stmt = stmt.where(or_(Experiment.code.ilike(like, escape="\\"),
                              *(getattr(Experiment, f).ilike(like, escape="\\") for f in TEXT_SEARCH_FIELDS)))
    if min_temp is not None:
        stmt = stmt.where(Experiment.operating_temp_c >= min_temp)
    if max_temp is not None:
        stmt = stmt.where(Experiment.operating_temp_c <= max_temp)
    if max_asr is not None:
        stmt = stmt.where(Experiment.asr_ohm_cm2 <= max_asr)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Experiment.submitted_at.desc(), Experiment.code.desc())
                      .limit(min(limit, 1000)).offset(offset))
    return {"total": total, "items": [experiment_out(e, viewer_internal=user.is_internal) for e in rows]}


@router.get("/similar")
def similar(db: DB, user: InternalUser, params: Annotated[list[str], Query()] = []) -> list[dict]:  # noqa: B006
    """`params=sintering_temp_c:1250&params=electrolyte_thickness_um:6` -> nearest approved experiments."""
    parsed = {}
    for p in params[:20]:
        k, _, v = p.partition(":")
        if k in DESIGN_SPACE:
            value, problem = coerce_value(FIELDS_BY_KEY[k], v)
            if value is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{k}: {problem or 'a number is required'}")
            parsed[k] = float(value)
    if len(parsed) < 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Provide at least 3 design variables")
    return similar_experiments(db, parsed)


@router.get("/{experiment_id}")
def get_experiment(experiment_id: str, db: DB, user: CurrentUser) -> dict:
    return experiment_out(get_scoped(db, Experiment, experiment_id, user), detail=True, viewer_internal=user.is_internal)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_manual(body: ManualCreate, db: DB, user: Reviewer) -> dict:
    org = require_known_org(db, body.organization, allow_internal=True)
    values, _ = _coerce_all(body.values)
    if body.document_id:
        get_scoped(db, Document, body.document_id, user)
    exp = Experiment(code=next_experiment_code(db), organization=org, source="manual",
                     document_id=body.document_id, created_by_id=user.id, extraction=None)
    db.add(exp)
    _apply(exp, values)
    db.flush()
    audit.record(db, actor=user, action="create_manual", entity_type="experiment", entity_id=exp.id,
                 organization=exp.organization, details={"values": {k: v for k, v in values.items() if v is not None}})
    db.commit()
    return experiment_out(exp, detail=True)


@router.patch("/{experiment_id}")
def update_draft(experiment_id: str, body: FieldValues, db: DB, user: Reviewer) -> dict:
    exp = get_scoped(db, Experiment, experiment_id, user)
    _pending(exp)
    values, problems = _coerce_all(body.values)
    changes = _apply(exp, values)
    if changes:
        audit.record(db, actor=user, action="edit_draft", entity_type="experiment", entity_id=exp.id,
                     organization=exp.organization, details={"changes": changes})
    db.commit()
    return {**experiment_out(exp, detail=True), "warnings": problems}


@router.post("/{experiment_id}/approve")
def approve(experiment_id: str, body: ApproveBody, db: DB, user: Reviewer) -> dict:
    exp = get_scoped(db, Experiment, experiment_id, user)
    _pending(exp)
    values, problems = _coerce_all(body.values)
    # Re-validate the full final record, not just the fields edited in this request.
    final = {**exp.field_values(), **values}
    for key, v in final.items():
        _, problem = coerce_value(FIELDS_BY_KEY[key], v)
        if problem:
            problems.setdefault(key, problem)
    if problems and not body.acknowledge_warnings:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            {"message": "Some values look implausible. Confirm to approve anyway.", "warnings": problems})

    changes = _apply(exp, values)
    ai_proposed = {k: m.get("value") for k, m in (exp.extraction or {}).items()}
    final_values = exp.field_values()
    ai_vs_final = audit.diff(ai_proposed, {k: final_values[k] for k in ai_proposed}) if ai_proposed else {}

    exp.status = ExperimentStatus.approved.value
    exp.reviewed_by_id, exp.reviewed_at = user.id, datetime.now(timezone.utc)
    exp.review_comment = body.comment
    db.flush()

    rag.index_experiment(db, exp)
    doc = exp.document
    if doc is not None:
        already = db.scalar(select(func.count()).select_from(Chunk)
                            .where(Chunk.document_id == doc.id, Chunk.experiment_id.is_(None)))
        if not already:
            rag.index_document(db, doc)
        if all(e.status != ExperimentStatus.pending_review.value for e in doc.experiments):
            doc.status = DocumentStatus.reviewed.value

    audit.record(db, actor=user, action="approve", entity_type="experiment", entity_id=exp.id,
                 organization=exp.organization, details={
                     "code": exp.code, "edits_in_request": changes, "ai_vs_final": ai_vs_final,
                     "ai_fields_corrected": sorted(ai_vs_final), "acknowledged_warnings": problems or None,
                     "comment": body.comment})
    db.commit()
    return experiment_out(exp, detail=True)


@router.post("/{experiment_id}/reject")
def reject(experiment_id: str, body: RejectBody, db: DB, user: Reviewer) -> dict:
    exp = get_scoped(db, Experiment, experiment_id, user)
    _pending(exp)
    exp.status = ExperimentStatus.rejected.value
    exp.reviewed_by_id, exp.reviewed_at, exp.review_comment = user.id, datetime.now(timezone.utc), body.reason
    doc = exp.document
    if doc is not None and all(e.status != ExperimentStatus.pending_review.value for e in doc.experiments):
        doc.status = DocumentStatus.reviewed.value
    audit.record(db, actor=user, action="reject", entity_type="experiment", entity_id=exp.id,
                 organization=exp.organization, details={"code": exp.code, "reason": body.reason})
    db.commit()
    return experiment_out(exp, detail=True)
