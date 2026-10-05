import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .core.config import get_settings
from .core.database import Base
from .experiment_schema import FIELD_SPECS

settings = get_settings()

if settings.is_postgres:
    from pgvector.sqlalchemy import Vector

    EmbeddingType: Any = Vector(settings.embedding_dim)
else:  # SQLite dev/test: store vectors as JSON, similarity computed in NumPy
    EmbeddingType = JSON

INTERNAL_ORG = "internal"


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    partner = "partner"        # external lab researcher: uploads, sees only own org's data
    scientist = "scientist"    # internal: reviews/approves extractions, runs recommender and Q&A
    leadership = "leadership"  # internal: read-only dashboards, registry and Q&A
    admin = "admin"            # internal: everything, including audit log


INTERNAL_ROLES = {Role.scientist, Role.leadership, Role.admin}


class DocumentStatus(str, enum.Enum):
    uploaded = "uploaded"
    extracting = "extracting"
    needs_review = "needs_review"
    reviewed = "reviewed"
    failed = "failed"
    indexed = "indexed"  # internal reports: embedded for Q&A, no extraction


class ExperimentStatus(str, enum.Enum):
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subject: Mapped[str] = mapped_column(String(255), unique=True, index=True)  # Cognito `sub`
    email: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(32))
    organization: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @property
    def is_internal(self) -> bool:
        return Role(self.role) in INTERNAL_ROLES


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="partner_report")  # partner_report | internal_report
    title: Mapped[str] = mapped_column(String(512))
    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_key: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(32), default=DocumentStatus.uploaded.value, index=True)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extraction_notes: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    uploaded_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    uploaded_by: Mapped[User] = relationship()
    experiments: Mapped[list["Experiment"]] = relationship(back_populates="document")


_SQL_TYPES = {"str": lambda: Text(), "float": Float, "int": Integer, "date": Date}


class ExperimentFieldsMixin:
    """Columns generated from FIELD_SPECS (see experiment_schema.py)."""


for _spec in FIELD_SPECS:
    setattr(ExperimentFieldsMixin, _spec.key, mapped_column(_SQL_TYPES[_spec.type](), nullable=True))


class Experiment(ExperimentFieldsMixin, Base):
    __tablename__ = "experiments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # CL-0001
    organization: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default=ExperimentStatus.pending_review.value, index=True)
    source: Mapped[str] = mapped_column(String(32), default="extracted")  # extracted | manual | seed
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), index=True)

    # Raw curves: {"freq_hz": [...], "z_real": [...], "z_imag": [...]} and
    # {"current_density_a_cm2": [...], "voltage_v": [...]}
    eis_data: Mapped[dict | None] = mapped_column(JSON)
    iv_data: Mapped[dict | None] = mapped_column(JSON)

    # What the AI proposed: {field: {"value", "confidence", "evidence", "evidence_verified", "problem"}}
    extraction: Mapped[dict | None] = mapped_column(JSON)
    completeness: Mapped[float] = mapped_column(Float, default=0.0)

    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    document: Mapped[Document | None] = relationship(back_populates="experiments")
    reviewed_by: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_id])

    def field_values(self) -> dict[str, Any]:
        return {s.key: getattr(self, s.key) for s in FIELD_SPECS}


class Chunk(Base):
    """A retrievable passage for cited Q&A: a slice of an approved report, or an approved experiment record."""

    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    experiment_id: Mapped[str | None] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    source_label: Mapped[str] = mapped_column(String(512))
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(EmbeddingType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    if settings.is_postgres:
        __table_args__ = (
            Index(
                "ix_chunks_embedding_hnsw",
                "embedding",
                postgresql_using="hnsw",
                postgresql_with={"m": 16, "ef_construction": 64},
                postgresql_ops={"embedding": "vector_cosine_ops"},
            ),
        )


class AuditLog(Base):
    """Append-only record of every upload, AI extraction, human edit/approval, Q&A query and recommendation."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), index=True)  # None = system/AI
    actor_email: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(36), index=True)
    organization: Mapped[str | None] = mapped_column(String(64), index=True)
    details: Mapped[dict | None] = mapped_column(JSON)


__all__ = [
    "AuditLog", "Chunk", "Document", "DocumentStatus", "Experiment", "ExperimentStatus",
    "INTERNAL_ORG", "INTERNAL_ROLES", "Role", "User",
]
