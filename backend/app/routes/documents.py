from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile

from app.config import settings
from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.common import Page
from app.schemas.documents import DocumentOut
from app.services.documents import (
    archive_document,
    require_university_wide_permission,
    processing_note,
    publish_document,
    replace_document,
    upload_document,
)
from app.services.providers import get_supabase_client
from app.services.supabase_client import SupabaseClient

router = APIRouter(prefix="/documents", tags=["documents"])
STAFF_ROLES = ("faculty", "authority")
ALL_SIGNED_IN = ("student", "faculty", "authority", "management")


def _to_out(row: dict) -> DocumentOut:
    data = dict(row)
    data["processing_note"] = processing_note(row, openai_configured=bool(settings.openai_api_key))
    return DocumentOut(**data)


def _check_form(visibility: str, scope: str) -> None:
    if visibility not in ("public_students", "staff_only"):
        raise HTTPException(422, "visibility must be public_students or staff_only")
    if scope not in ("campus", "university_wide"):
        raise HTTPException(422, "scope must be campus or university_wide")


@router.post("", response_model=DocumentOut, status_code=202)
async def upload(
    response: Response,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    title: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    visibility: Annotated[str, Form()] = "public_students",
    scope: Annotated[str, Form()] = "campus",
    department_id: Annotated[UUID | None, Form()] = None,
    sb: SupabaseClient = Depends(get_supabase_client),
):
    """Stores the PDF and queues it for processing. Returns 202; poll GET /documents/{id}."""
    _check_form(visibility, scope)
    require_university_wide_permission(session.user, scope)
    data = await file.read(settings.max_upload_bytes + 1)
    row = await upload_document(
        sb=sb,
        uploader=session.user,
        title=title,
        visibility=visibility,
        scope=scope,
        department_id=department_id,
        filename=file.filename,
        content_type=file.content_type,
        data=data,
        max_bytes=settings.max_upload_bytes,
        storage_bucket=settings.supabase_storage_bucket,
    )
    response.headers["Location"] = f"{settings.api_v1_prefix}/documents/{row['id']}"
    return _to_out(row)


@router.post("/{document_id}/replace", response_model=DocumentOut, status_code=202)
async def replace(
    document_id: UUID,
    response: Response,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    sb: SupabaseClient = Depends(get_supabase_client),
):
    """Uploads a new version. It stays a draft until published; publishing archives the old version."""
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
        storage_bucket=settings.supabase_storage_bucket,
    )
    response.headers["Location"] = f"{settings.api_v1_prefix}/documents/{row['id']}"
    return _to_out(row)


@router.post("/{document_id}/publish", response_model=DocumentOut)
async def publish(
    document_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    row = await publish_document(sb=sb, user=session.user, access_token=session.access_token, document_id=document_id)
    return _to_out(row)


@router.post("/{document_id}/archive", response_model=DocumentOut)
async def archive(
    document_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    row = await archive_document(sb=sb, user=session.user, access_token=session.access_token, document_id=document_id)
    return _to_out(row)


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*ALL_SIGNED_IN))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    rows = await sb.select_as_user(session.access_token, "documents", {"select": "*", "id": f"eq.{document_id}"})
    if not rows:
        raise HTTPException(404, "Document not found")
    return _to_out(rows[0])


@router.get("", response_model=Page[DocumentOut])
async def list_documents(
    session: Annotated[CurrentSession, Depends(session_with_roles(*ALL_SIGNED_IN))],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    processing_status: Literal["pending", "processing", "ready", "failed"] | None = None,
    publication_status: Literal["draft", "published", "archived"] | None = None,
    visibility: Literal["public_students", "staff_only"] | None = None,
    scope: Literal["campus", "university_wide"] | None = None,
    campus_id: UUID | None = None,
    department_id: UUID | None = None,
    sb: SupabaseClient = Depends(get_supabase_client),
):
    """Documents the caller may see. Filters narrow the results; they never widen access."""
    filters = {"order": "created_at.desc"}
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
    return Page[DocumentOut](items=[_to_out(r) for r in rows], total=total, limit=limit, offset=offset)
