from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Response, UploadFile

from app.config import settings
from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.common import Page
from app.schemas.documents import (
    DocumentOut,
    DocumentUpdateIn,
    KnowledgeStatsOut,
    TextContentCreateIn,
    TextContentUpdateIn,
)
from app.services.documents import (
    archive_document,
    create_text_content,
    delete_document,
    get_knowledge_stats,
    processing_note,
    publish_document,
    replace_document,
    reprocess_document,
    require_university_wide_permission,
    unpublish_document,
    update_document_metadata,
    update_text_content,
    upload_document,
)
from app.services.postgres_client import PostgresClient
from app.services.providers import get_data_client

router = APIRouter(prefix="/documents", tags=["documents"])
STAFF_ROLES = ("faculty", "authority", "management", "super_admin")
KNOWLEDGE_MANAGERS = ("authority", "management", "super_admin")
ALL_SIGNED_IN = ("student", "faculty", "authority", "management", "super_admin")


def _to_out(row: dict) -> DocumentOut:
    data = dict(row)
    data["processing_note"] = processing_note(row, ai_configured=bool(settings.gemini_api_key))
    if "tags" in data and not isinstance(data["tags"], list):
        data["tags"] = []
    return DocumentOut(**data)


def _check_form(visibility: str, scope: str) -> None:
    if visibility not in ("public_students", "staff_only"):
        raise HTTPException(422, "visibility must be public_students or staff_only")
    if scope not in ("campus", "university_wide"):
        raise HTTPException(422, "scope must be campus or university_wide")


@router.get("/stats/overview", response_model=KnowledgeStatsOut)
async def knowledge_stats(
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Returns overview statistics of knowledge base documents and text content."""
    stats = await get_knowledge_stats(sb, session.access_token)
    return KnowledgeStatsOut(**stats)


@router.post("", response_model=DocumentOut, status_code=202)
async def upload(
    response: Response,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    title: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    visibility: Annotated[str, Form()] = "public_students",
    scope: Annotated[str, Form()] = "campus",
    category: Annotated[str, Form()] = "General",
    description: Annotated[str | None, Form()] = None,
    department_id: Annotated[UUID | None, Form()] = None,
    effective_date: Annotated[str | None, Form()] = None,
    expiry_date: Annotated[str | None, Form()] = None,
    sb: PostgresClient = Depends(get_data_client),
):
    """Stores the document file and queues it for processing. Supports PDF, DOCX, TXT."""
    _check_form(visibility, scope)
    require_university_wide_permission(session.user, scope)
    data = await file.read(settings.max_upload_bytes + 1)
    row = await upload_document(
        sb=sb,
        uploader=session.user,
        title=title,
        visibility=visibility,
        scope=scope,
        category=category,
        description=description,
        department_id=department_id,
        filename=file.filename,
        content_type=file.content_type,
        data=data,
        max_bytes=settings.max_upload_bytes,
        storage_bucket=settings.r2_bucket,
        effective_date=effective_date,
        expiry_date=expiry_date,
    )
    response.headers["Location"] = f"{settings.api_v1_prefix}/documents/{row['id']}"
    return _to_out(row)


@router.post("/content", response_model=DocumentOut, status_code=202)
async def add_text_content(
    response: Response,
    body: TextContentCreateIn,
    session: Annotated[CurrentSession, Depends(session_with_roles(*KNOWLEDGE_MANAGERS))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Management: Adds text-based university policy or guidelines directly."""
    _check_form(body.visibility, body.scope)
    require_university_wide_permission(session.user, body.scope)
    row = await create_text_content(
        sb=sb,
        user=session.user,
        title=body.title,
        content=body.content,
        category=body.category,
        description=body.description,
        department_id=body.department_id,
        scope=body.scope,
        visibility=body.visibility,
        publication_status=body.publication_status,
        effective_date=body.effective_date,
        expiry_date=body.expiry_date,
        tags=body.tags,
    )
    response.headers["Location"] = f"{settings.api_v1_prefix}/documents/{row['id']}"
    return _to_out(row)


@router.patch("/content/{document_id}", response_model=DocumentOut)
async def update_content(
    document_id: UUID,
    body: TextContentUpdateIn,
    session: Annotated[CurrentSession, Depends(session_with_roles(*KNOWLEDGE_MANAGERS))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Management: Edits existing text-based knowledge content and re-queues embedding if needed."""
    if body.visibility and body.scope:
        _check_form(body.visibility, body.scope)
    row = await update_text_content(
        sb=sb,
        user=session.user,
        access_token=session.access_token,
        document_id=document_id,
        title=body.title,
        content=body.content,
        category=body.category,
        description=body.description,
        department_id=body.department_id,
        scope=body.scope,
        visibility=body.visibility,
        publication_status=body.publication_status,
        effective_date=body.effective_date,
        expiry_date=body.expiry_date,
        tags=body.tags,
    )
    return _to_out(row)


@router.patch("/{document_id}", response_model=DocumentOut)
async def update_metadata(
    document_id: UUID,
    body: DocumentUpdateIn,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Updates metadata (title, category, description, dates, tags) for an existing document."""
    row = await update_document_metadata(
        sb=sb,
        user=session.user,
        access_token=session.access_token,
        document_id=document_id,
        title=body.title,
        category=body.category,
        description=body.description,
        department_id=body.department_id,
        scope=body.scope,
        visibility=body.visibility,
        publication_status=body.publication_status,
        effective_date=body.effective_date,
        expiry_date=body.expiry_date,
        tags=body.tags,
    )
    return _to_out(row)


@router.post("/{document_id}/replace", response_model=DocumentOut, status_code=202)
async def replace(
    document_id: UUID,
    response: Response,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    sb: PostgresClient = Depends(get_data_client),
):
    """Uploads a new file version. It stays draft until published; publishing archives old version."""
    data = await file.read(settings.max_upload_bytes + 1)
    row = await replace_document(
        sb=sb,
        user=session.user,
        access_token=session.access_token,
        document_id=document_id,
        title=title,
        content_type=file.content_type,
        filename=file.filename,
        data=data,
        max_bytes=settings.max_upload_bytes,
        storage_bucket=settings.r2_bucket,
    )
    response.headers["Location"] = f"{settings.api_v1_prefix}/documents/{row['id']}"
    return _to_out(row)


@router.post("/{document_id}/publish", response_model=DocumentOut)
async def publish(
    document_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    sb: PostgresClient = Depends(get_data_client),
):
    row = await publish_document(
        sb=sb, user=session.user, access_token=session.access_token, document_id=document_id
    )
    return _to_out(row)


@router.post("/{document_id}/unpublish", response_model=DocumentOut)
async def unpublish(
    document_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Unpublishes a document or content item, moving it back to draft status."""
    row = await unpublish_document(
        sb=sb, user=session.user, access_token=session.access_token, document_id=document_id
    )
    return _to_out(row)


@router.post("/{document_id}/reprocess", response_model=DocumentOut)
async def reprocess(
    document_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Rebuilds document text chunks and vector embeddings."""
    row = await reprocess_document(
        sb=sb, user=session.user, access_token=session.access_token, document_id=document_id
    )
    return _to_out(row)


@router.post("/{document_id}/archive", response_model=DocumentOut)
async def archive(
    document_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    sb: PostgresClient = Depends(get_data_client),
):
    row = await archive_document(
        sb=sb, user=session.user, access_token=session.access_token, document_id=document_id
    )
    return _to_out(row)


@router.delete("/{document_id}")
async def remove(
    document_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Deletes a document or content item and removes its indexed vector chunks."""
    result = await delete_document(
        sb=sb,
        user=session.user,
        access_token=session.access_token,
        document_id=document_id,
        storage_bucket=settings.r2_bucket,
    )
    return result


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*ALL_SIGNED_IN))],
    sb: PostgresClient = Depends(get_data_client),
):
    rows = await sb.select_as_user(
        session.access_token, "documents", {"select": "*", "id": f"eq.{document_id}"}
    )
    if not rows:
        raise HTTPException(404, "Document not found")
    return _to_out(rows[0])


@router.get("", response_model=Page[DocumentOut])
async def list_documents(
    session: Annotated[CurrentSession, Depends(session_with_roles(*ALL_SIGNED_IN))],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    item_type: Literal["file", "text_content"] | None = None,
    category: str | None = None,
    search: str | None = None,
    processing_status: Literal["pending", "processing", "ready", "failed"] | None = None,
    publication_status: Literal["draft", "published", "archived"] | None = None,
    visibility: Literal["public_students", "staff_only"] | None = None,
    scope: Literal["campus", "university_wide"] | None = None,
    campus_id: UUID | None = None,
    department_id: UUID | None = None,
    sb: PostgresClient = Depends(get_data_client),
):
    """Documents and content the caller may see. Filters narrow results; never widen access."""
    filters = {"order": "created_at.desc"}
    if item_type:
        filters["item_type"] = f"eq.{item_type}"
    if category:
        filters["category"] = f"eq.{category}"
    if processing_status:
        filters["processing_status"] = f"eq.{processing_status}"
    if publication_status:
        filters["publication_status"] = f"eq.{publication_status}"
    if visibility:
        filters["visibility"] = f"eq.{visibility}"
    if scope:
        filters["scope"] = f"eq.{scope}"
    if campus_id:
        filters["campus_id"] = f"eq.{campus_id}"
    if department_id:
        filters["department_id"] = f"eq.{department_id}"

    rows, total = await sb.select_page_as_user(
        session.access_token, "documents", {"select": "*", **filters}, limit, offset
    )
    if search:
        s = search.lower()
        rows = [
            r
            for r in rows
            if s in r.get("title", "").lower()
            or s in r.get("category", "").lower()
            or s in r.get("description", "").lower()
            or s in r.get("raw_content", "").lower()
        ]
        total = len(rows)

    return Page[DocumentOut](
        items=[_to_out(r) for r in rows], total=total, limit=limit, offset=offset
    )
