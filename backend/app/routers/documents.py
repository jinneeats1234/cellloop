import hashlib
import logging
import re
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import audit
from ..core.errors import user_message
from ..core import ratelimit
from ..core.access import get_scoped, require_known_org, scope
from ..core.validation import clean_query
from ..core.security import CurrentUser, Reviewer, Uploader
from ..core.config import get_settings
from ..core.database import SessionLocal, get_db
from ..models import INTERNAL_ORG, Document, DocumentStatus
from ..serializers import document_out
from ..services import rag
from ..services.extraction import run_extraction
from ..services.parsing import ALLOWED_EXTENSIONS, check_signature, parse_file, safe_content_type
from ..services.storage import get_storage

router = APIRouter(prefix="/api/documents", tags=["documents"])
log = logging.getLogger(__name__)
settings = get_settings()
DB = Annotated[Session, Depends(get_db)]


def _safe_filename(name: str) -> str:
    """Basename only, ASCII-safe, no leading dots (no hidden files, no '..')."""
    base = re.split(r"[\\/]", name or "upload")[-1]
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).lstrip(". ")
    base = re.sub(r"\.{2,}", ".", base)
    return base[:200] or "upload"


def _index_internal_report(document_id: str) -> None:
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        parsed = parse_file(doc.filename, get_storage().get(doc.storage_key))
        doc.extracted_text = parsed.text
        n = rag.index_document(db, doc)
        doc.status = DocumentStatus.indexed.value
        doc.extraction_notes = f"Indexed {n} passages for Q&A."
        db.commit()
    except Exception as exc:
        log.exception("Indexing internal report %s failed", document_id)
        db.rollback()
        doc = db.get(Document, document_id)
        doc.status, doc.error = DocumentStatus.failed.value, user_message(exc)[:2000]
        db.commit()
    finally:
        db.close()


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload(
    background: BackgroundTasks,
    db: DB,
    user: Uploader,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=500)] = None,
    kind: Annotated[str, Form(max_length=32)] = "partner_report",
    organization: Annotated[str | None, Form(max_length=64)] = None,
) -> dict:
    ratelimit.check(f"upload:{user.id}", settings.rate_limit_upload_per_min)
    filename = _safe_filename(file.filename or "upload")
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")
    limit = settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"File exceeds {settings.max_upload_mb} MB")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    bad_signature = check_signature(filename, data)
    if bad_signature:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, bad_signature)
    if title is not None:
        title = clean_query(title, "Title", 500)

    # Partners can only file under their own organization. Internal staff may log reports
    # that partners emailed in, on the partner's behalf, or upload internal reports for Q&A.
    if user.is_internal:
        if kind == "internal_report":
            org = INTERNAL_ORG
        elif organization and organization != INTERNAL_ORG:
            org = require_known_org(db, organization)
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose the partner organization this report came from")
    else:
        kind, org = "partner_report", user.organization
    if kind not in ("partner_report", "internal_report"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid document kind")

    sha = hashlib.sha256(data).hexdigest()
    dup = db.scalar(select(Document).where(Document.sha256 == sha, Document.organization == org))
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            {"message": "This exact file was already submitted", "document_id": dup.id})

    doc = Document(organization=org, kind=kind, title=(title or filename)[:500], filename=filename,
                   content_type=safe_content_type(filename),
                   size_bytes=len(data), sha256=sha, storage_key="", uploaded_by_id=user.id)
    db.add(doc)
    db.flush()
    doc.storage_key = f"{org}/{doc.id}/{filename}"
    get_storage().put(doc.storage_key, data, doc.content_type)
    audit.record(db, actor=user, action="upload", entity_type="document", entity_id=doc.id, organization=org,
                 details={"filename": filename, "kind": kind, "size_bytes": len(data), "sha256": sha})
    db.commit()

    background.add_task(_index_internal_report if kind == "internal_report" else run_extraction, doc.id)
    return document_out(doc, viewer_internal=user.is_internal)


@router.get("")
def list_documents(db: DB, user: CurrentUser, status_: Annotated[str | None, Query(alias="status", max_length=32)] = None,
                   limit: Annotated[int, Query(ge=1, le=500)] = 200) -> list[dict]:
    stmt = scope(select(Document), Document, user).order_by(Document.uploaded_at.desc()).limit(limit)
    if status_:
        stmt = stmt.where(Document.status == status_)
    return [document_out(d, viewer_internal=user.is_internal) for d in db.scalars(stmt)]


@router.get("/{document_id}")
def get_document(document_id: str, db: DB, user: CurrentUser) -> dict:
    return document_out(get_scoped(db, Document, document_id, user), include_text=True, viewer_internal=user.is_internal)


@router.get("/{document_id}/file")
def download(document_id: str, db: DB, user: CurrentUser) -> Response:
    doc = get_scoped(db, Document, document_id, user)
    audit.record(db, actor=user, action="download", entity_type="document", entity_id=doc.id,
                 organization=doc.organization)
    db.commit()
    data = get_storage().get(doc.storage_key)
    # Type comes from the extension (never the uploader), and the file is always an attachment
    # with a sandboxing CSP: even a malicious file can't execute in the app's origin.
    return Response(content=data, media_type=safe_content_type(doc.filename), headers={
        "Content-Disposition": f'attachment; filename="{doc.filename}"',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    })


@router.post("/{document_id}/reextract")
def reextract(document_id: str, background: BackgroundTasks, db: DB, user: Reviewer) -> dict:
    doc = get_scoped(db, Document, document_id, user)
    if doc.kind != "partner_report":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only partner reports are extracted")
    if any(e.status == "approved" for e in doc.experiments):
        raise HTTPException(status.HTTP_409_CONFLICT, "Records from this document are already approved")
    for e in list(doc.experiments):
        db.delete(e)
    doc.status, doc.error = DocumentStatus.uploaded.value, None
    audit.record(db, actor=user, action="reextract", entity_type="document", entity_id=doc.id,
                 organization=doc.organization)
    db.commit()
    background.add_task(run_extraction, doc.id)
    return document_out(doc, viewer_internal=user.is_internal)
