from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.notifications import NotificationOut
from app.services.notifications import mark_notification_read
from app.services.providers import get_supabase_client
from app.services.supabase_client import SupabaseClient

router = APIRouter(prefix="/notifications", tags=["notifications"])
ANY_SIGNED_IN = ("student", "faculty", "authority", "management")


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    session: Annotated[CurrentSession, Depends(session_with_roles(*ANY_SIGNED_IN))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    return await sb.select_as_user(
        session.access_token,
        "notifications",
        {"select": "*", "order": "created_at.desc"},
    )


@router.patch("/{notification_id}/read", response_model=NotificationOut)
async def read_notification(
    notification_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*ANY_SIGNED_IN))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    return await mark_notification_read(sb=sb, access_token=session.access_token, notification_id=notification_id)
