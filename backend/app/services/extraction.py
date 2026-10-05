"""Partner report -> draft experiment records awaiting human review.

Pipeline: parse file -> Claude structured extraction -> type/range validation ->
evidence verification (each quoted snippet must appear in the source, else the
field is flagged as possibly hallucinated) -> curve analysis -> draft records + audit.
Nothing becomes an approved record without a scientist's sign-off.
"""

import logging
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import audit
from ..core.errors import user_message
from ..core.database import SessionLocal
from ..experiment_schema import FIELD_SPECS, FIELDS_BY_KEY, coerce_value, completeness
from ..models import Document, DocumentStatus, Experiment, ExperimentStatus
from .impedance import analyze_eis, analyze_iv
from .llm import get_llm
from .parsing import parse_file
from .storage import get_storage

log = logging.getLogger(__name__)

MAX_LLM_CHARS = 400_000  # ~100k tokens; well inside Claude's context window


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def next_experiment_code(db: Session) -> str:
    n = db.scalar(select(func.count()).select_from(Experiment)) or 0
    while True:
        n += 1
        code = f"CL-{n:04d}"
        if not db.scalar(select(Experiment.id).where(Experiment.code == code)):
            return code


def validate_extraction(raw: dict[str, Any], source_text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (values, extraction_meta) for one AI-proposed experiment."""
    haystack = _norm(source_text)
    values: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    for spec in FIELD_SPECS:
        item = raw.get(spec.key) or {}
        value, problem = coerce_value(spec, item.get("value"))
        evidence = item.get("evidence")
        verified = bool(evidence) and _norm(evidence) in haystack
        confidence = item.get("confidence", "low")
        if value is not None and not verified:
            confidence = "low"
            problem = problem or "Evidence quote not found in source document — verify manually"
        values[spec.key] = value
        meta[spec.key] = {
            "value": value.isoformat() if hasattr(value, "isoformat") else value,
            "confidence": confidence if value is not None else "low",
            "evidence": evidence,
            "evidence_verified": verified,
            "problem": problem,
        }
    return values, meta


def _apply_curve_analysis(values: dict[str, Any], meta: dict[str, Any], eis: dict | None, iv: dict | None) -> None:
    """Fill gaps from raw curves (never overwrite what the report states) and record provenance."""
    derived: dict[str, Any] = {}
    if eis:
        derived.update(analyze_eis(eis, values.get("active_area_cm2")))
    if iv:
        derived.update({k: v for k, v in analyze_iv(iv).items() if k != "iv_asr_ohm_cm2"})
    for key in ("asr_ohm_cm2", "ohmic_asr_ohm_cm2", "polarization_asr_ohm_cm2", "peak_power_density_w_cm2", "ocv_v"):
        if key in derived and values.get(key) is None:
            values[key] = derived[key]
            meta[key] = {"value": derived[key], "confidence": "medium", "evidence": None,
                         "evidence_verified": True, "problem": None,
                         "derived_from": "EIS spectrum" if "asr" in key else "polarization curve"}
    reported = values.get("asr_ohm_cm2")
    if reported and derived.get("asr_ohm_cm2") and abs(reported - derived["asr_ohm_cm2"]) / reported > 0.2:
        meta["asr_ohm_cm2"]["problem"] = (
            f"Reported ASR {reported} differs >20% from the EIS-derived {derived['asr_ohm_cm2']} Ω·cm²"
        )


def run_extraction(document_id: str) -> None:
    """Background task. Uses its own DB session."""
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            return
        doc.status = DocumentStatus.extracting.value
        db.commit()
        try:
            data = get_storage().get(doc.storage_key)
            parsed = parse_file(doc.filename, data)
            doc.extracted_text = parsed.text
            text = parsed.text[:MAX_LLM_CHARS]
            if len(parsed.text) > MAX_LLM_CHARS:
                parsed.warnings.append("Document truncated for extraction; review remaining pages manually.")

            result = get_llm().extract(text, doc.filename) if text.strip() else {"experiments": [], "extraction_notes": ""}
            proposals = result.get("experiments", [])

            # A bare EIS/IV export with no metadata still becomes a (mostly empty) draft.
            if not proposals and (parsed.eis_data or parsed.iv_data):
                proposals = [{}]

            created = []
            for raw in proposals:
                values, meta = validate_extraction(raw, parsed.text)
                _apply_curve_analysis(values, meta, parsed.eis_data, parsed.iv_data)
                score, _ = completeness(values)
                exp = Experiment(
                    code=next_experiment_code(db),
                    organization=doc.organization,
                    status=ExperimentStatus.pending_review.value,
                    source="extracted",
                    document_id=doc.id,
                    eis_data=parsed.eis_data,
                    iv_data=parsed.iv_data,
                    extraction=meta,
                    completeness=score,
                    created_by_id=doc.uploaded_by_id,
                    submitted_at=doc.uploaded_at,
                    **values,
                )
                db.add(exp)
                db.flush()
                created.append(exp)
                audit.record(
                    db, actor=None, actor_label=audit.AI_ACTOR, action="ai_extraction", entity_type="experiment",
                    entity_id=exp.id, organization=doc.organization,
                    details={"document_id": doc.id, "code": exp.code,
                             "proposed": {k: m["value"] for k, m in meta.items() if m["value"] is not None},
                             "low_confidence": [k for k, m in meta.items()
                                                if m["value"] is not None and m["confidence"] == "low"]},
                )

            notes = [result.get("extraction_notes") or "", *parsed.warnings]
            if not created:
                notes.append("No experiments could be extracted. A scientist can create a record manually.")
            doc.extraction_notes = "\n".join(n for n in notes if n)
            doc.status = DocumentStatus.needs_review.value
            db.commit()
        except Exception as exc:  # surface the failure to the user instead of silently dropping it
            log.exception("Extraction failed for %s", document_id)
            db.rollback()
            doc = db.get(Document, document_id)
            doc.status = DocumentStatus.failed.value
            doc.error = user_message(exc)[:2000]
            audit.record(db, actor=None, actor_label=audit.AI_ACTOR, action="ai_extraction_failed",
                         entity_type="document", entity_id=doc.id, organization=doc.organization,
                         details={"error": doc.error, "exception": f"{type(exc).__name__}: {exc}"[:2000]})
            db.commit()
    finally:
        db.close()


def field_label(key: str) -> str:
    return FIELDS_BY_KEY[key].label if key in FIELDS_BY_KEY else key
