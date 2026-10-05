"""Retrieval-augmented, citation-only Q&A over approved program knowledge.

Only approved experiment records and reports are indexed. Retrieval is tenant-scoped
in the query itself. The answer is accepted only if it cites at least one retrieved
source; otherwise the system declines rather than letting the model speak unsupported.
"""

import re
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..experiment_schema import FIELD_SPECS
from ..models import Chunk, Document, Experiment, User
from .llm import get_llm

settings = get_settings()

CHUNK_CHARS = 1400
CHUNK_OVERLAP = 200
DECLINE_MESSAGE = (
    "I can't answer that from CellLoop's approved records. No indexed report or experiment "
    "contains enough evidence, and I only answer with citations."
)


def chunk_text(text: str) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, buf = [], ""
    for p in paras:
        while len(p) > CHUNK_CHARS:  # hard-split very long paragraphs
            chunks.append(p[:CHUNK_CHARS])
            p = p[CHUNK_CHARS - CHUNK_OVERLAP:]
        if len(buf) + len(p) + 2 > CHUNK_CHARS and buf:
            chunks.append(buf)
            buf = buf[-CHUNK_OVERLAP:] + "\n\n" + p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf:
        chunks.append(buf)
    return chunks


def experiment_summary(exp: Experiment) -> str:
    parts = [f"Experiment {exp.code} (organization: {exp.organization}, status: {exp.status})."]
    for spec in FIELD_SPECS:
        v = getattr(exp, spec.key)
        if v not in (None, ""):
            unit = f" {spec.unit}" if spec.unit else ""
            parts.append(f"{spec.label}: {v}{unit}.")
    return " ".join(parts)


def index_experiment(db: Session, exp: Experiment) -> None:
    db.query(Chunk).filter(Chunk.experiment_id == exp.id).delete()
    text = experiment_summary(exp)
    [vec] = get_llm().embed([text])
    db.add(Chunk(organization=exp.organization, experiment_id=exp.id, document_id=exp.document_id,
                 source_label=f"Experiment record {exp.code}", text=text, embedding=vec))


def index_document(db: Session, doc: Document) -> int:
    db.query(Chunk).filter(Chunk.document_id == doc.id, Chunk.experiment_id.is_(None)).delete()
    pieces = chunk_text(doc.extracted_text or "")
    if not pieces:
        return 0
    vectors = get_llm().embed(pieces)
    for i, (piece, vec) in enumerate(zip(pieces, vectors)):
        db.add(Chunk(organization=doc.organization, document_id=doc.id, chunk_index=i,
                     source_label=f"{doc.title} (part {i + 1}/{len(pieces)})", text=piece, embedding=vec))
    return len(pieces)


def retrieve(db: Session, user: User, query: str, k: int) -> list[tuple[Chunk, float]]:
    [qvec] = get_llm().embed([query])
    stmt = select(Chunk)
    if not user.is_internal:
        stmt = stmt.where(Chunk.organization == user.organization)

    if settings.is_postgres:
        dist = Chunk.embedding.cosine_distance(qvec)
        rows = db.execute(stmt.add_columns(dist.label("d")).order_by(dist).limit(k)).all()
        return [(c, 1.0 - float(d)) for c, d in rows]

    chunks = db.scalars(stmt).all()
    if not chunks:
        return []
    m = np.asarray([c.embedding for c in chunks], dtype=float)
    q = np.asarray(qvec, dtype=float)
    sims = m @ q / (np.linalg.norm(m, axis=1) * (np.linalg.norm(q) or 1.0) + 1e-12)
    order = np.argsort(-sims)[:k]
    return [(chunks[i], float(sims[i])) for i in order]


_CITE = re.compile(r"\[(S\d+)\]")


def answer_question(db: Session, user: User, question: str) -> dict[str, Any]:
    hits = [(c, s) for c, s in retrieve(db, user, question, settings.qa_top_k) if s >= settings.min_similarity]
    if not hits:
        return {"answered": False, "answer": DECLINE_MESSAGE, "citations": [], "reason": "no_relevant_sources"}

    sources = [{"id": f"S{i}", "label": c.source_label, "text": c.text} for i, (c, _) in enumerate(hits, start=1)]
    raw = get_llm().answer(question, sources)
    if raw.strip() == "INSUFFICIENT_EVIDENCE":
        return {"answered": False, "answer": DECLINE_MESSAGE, "citations": [], "reason": "model_insufficient_evidence"}

    valid_ids = {s["id"] for s in sources}
    cited = [sid for sid in dict.fromkeys(_CITE.findall(raw)) if sid in valid_ids]
    if not cited:
        return {"answered": False, "answer": DECLINE_MESSAGE, "citations": [], "reason": "answer_had_no_citations"}
    # Drop any citation markers that point at sources we never provided.
    answer = _CITE.sub(lambda m: m.group(0) if m.group(1) in valid_ids else "", raw)

    by_id = {f"S{i}": (c, s) for i, (c, s) in enumerate(hits, start=1)}
    citations = []
    for sid in cited:
        c, score = by_id[sid]
        citations.append({
            "id": sid, "label": c.source_label, "document_id": c.document_id, "experiment_id": c.experiment_id,
            "snippet": c.text[:600], "similarity": round(score, 3),
        })
    return {"answered": True, "answer": answer, "citations": citations, "reason": None}
