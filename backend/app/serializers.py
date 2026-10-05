from datetime import date, datetime
from typing import Any

from .experiment_schema import FIELD_SPECS
from .models import Document, Experiment
from .services.impedance import analyze_eis, analyze_iv
from .services.parsing import safe_content_type


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, (date, datetime)) else v


STAFF_LABEL = "CellLoop team"


def _person(user: Any, viewer_internal: bool) -> str | None:
    """Partners see their own colleagues' emails, but internal staff appear as 'CellLoop team'."""
    if user is None:
        return None
    return user.email if viewer_internal or not user.is_internal else STAFF_LABEL


def document_out(d: Document, *, include_text: bool = False, viewer_internal: bool = True) -> dict[str, Any]:
    out = {
        "id": d.id, "title": d.title, "filename": d.filename, "content_type": safe_content_type(d.filename),
        "size_bytes": d.size_bytes, "kind": d.kind, "organization": d.organization, "status": d.status,
        "extraction_notes": d.extraction_notes, "error": d.error, "uploaded_at": _iso(d.uploaded_at),
        "uploaded_by": _person(d.uploaded_by, viewer_internal),
        "experiment_ids": [e.id for e in d.experiments],
    }
    if include_text:
        out["extracted_text"] = d.extracted_text
    return out


def experiment_out(e: Experiment, *, detail: bool = False, viewer_internal: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": e.id, "code": e.code, "organization": e.organization, "status": e.status, "source": e.source,
        "document_id": e.document_id, "document_title": e.document.title if e.document else None,
        "completeness": round(e.completeness or 0.0, 3),
        "submitted_at": _iso(e.submitted_at), "reviewed_at": _iso(e.reviewed_at),
        "reviewed_by": _person(e.reviewed_by, viewer_internal), "review_comment": e.review_comment,
        "fields": {s.key: _iso(getattr(e, s.key)) for s in FIELD_SPECS},
        "has_eis": bool(e.eis_data), "has_iv": bool(e.iv_data),
    }
    if detail:
        out["extraction"] = e.extraction
        out["eis_data"] = e.eis_data
        out["iv_data"] = e.iv_data
        analysis: dict[str, Any] = {}
        if e.eis_data:
            analysis["eis"] = analyze_eis(e.eis_data, e.active_area_cm2)
        if e.iv_data:
            analysis["iv"] = analyze_iv(e.iv_data)
        out["analysis"] = analysis
    return out
