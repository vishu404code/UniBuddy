from typing import Annotated

from fastapi import APIRouter, Depends

from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.announcements import AnnouncementCreate, AnnouncementOut
from app.services.announcements import create_announcement
from app.services.providers import get_supabase_client
from app.services.supabase_client import SupabaseClient

router = APIRouter(prefix="/announcements", tags=["announcements"])


@router.get("", response_model=list[AnnouncementOut])
async def list_announcements(
    session: Annotated[CurrentSession, Depends(session_with_roles("student", "faculty", "authority", "management"))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    return await sb.select_as_user(
        session.access_token,
        "announcements",
        {"select": "*", "order": "created_at.desc"},
    )


@router.post("", response_model=AnnouncementOut, status_code=201)
async def publish_announcement(
    body: AnnouncementCreate,
    session: Annotated[CurrentSession, Depends(session_with_roles("faculty", "authority"))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    return await create_announcement(sb=sb, user=session.user, body=body)
