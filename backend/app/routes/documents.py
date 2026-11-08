from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.ai.openai_client import OpenAIClient
from app.config import settings
from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.documents import DocumentOut
from app.services.documents import ingest_document, publish_document
from app.services.providers import get_openai_client, get_supabase_client
from app.services.supabase_client import SupabaseClient

router = APIRouter(prefix="/documents", tags=["documents"])
STAFF_ROLES = ("faculty", "authority")


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    title: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    visibility: Annotated[str, Form()] = "public_students",
    scope: Annotated[str, Form()] = "campus",
    department_id: Annotated[UUID | None, Form()] = None,
    sb: SupabaseClient = Depends(get_supabase_client),
    ai: OpenAIClient = Depends(get_openai_client),
):
    if visibility not in ("public_students", "staff_only"):
        raise HTTPException(422, "visibility must be public_students or staff_only")
    if scope not in ("campus", "university_wide"):
        raise HTTPException(422, "scope must be campus or university_wide")

    data = await file.read(settings.max_upload_bytes + 1)
    return await ingest_document(
        sb=sb,
        ai=ai,
        uploader=session.user,
        title=title,
        visibility=visibility,
        scope=scope,
        department_id=department_id,
        filename=file.filename,
        content_type=file.content_type,
        data=data,
        max_bytes=settings.max_upload_bytes,
        chunk_max_chars=settings.chunk_max_chars,
        chunk_overlap_chars=settings.chunk_overlap_chars,
        storage_bucket=settings.supabase_storage_bucket,
    )


@router.post("/{document_id}/publish", response_model=DocumentOut)
async def publish(
    document_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    return await publish_document(sb=sb, user=session.user, access_token=session.access_token, document_id=document_id)


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    session: Annotated[CurrentSession, Depends(session_with_roles("student", *STAFF_ROLES, "management"))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    return await sb.select_as_user(
        session.access_token,
        "documents",
        {"select": "*", "order": "created_at.desc"},
    )
