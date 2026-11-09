from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.common import Page
from app.schemas.notifications import NotificationOut
from app.services.notifications import mark_notification_read
from app.services.providers import get_data_client
from app.services.postgres_client import PostgresClient

router = APIRouter(prefix="/notifications", tags=["notifications"])
ANY_SIGNED_IN = ("student", "faculty", "authority", "management")


@router.get("", response_model=Page[NotificationOut])
async def list_notifications(
    session: Annotated[CurrentSession, Depends(session_with_roles(*ANY_SIGNED_IN))],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    is_read: bool | None = None,
    sb: PostgresClient = Depends(get_data_client),
):
    filters = {"order": "created_at.desc"}
    if is_read is not None:
        filters["is_read"] = f"eq.{'true' if is_read else 'false'}"
    rows, total = await sb.select_page_as_user(
        session.access_token, "notifications", {"select": "*", **filters}, limit, offset
    )
    return Page[NotificationOut](items=rows, total=total, limit=limit, offset=offset)


@router.patch("/{notification_id}/read", response_model=NotificationOut)
async def read_notification(
    notification_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*ANY_SIGNED_IN))],
    sb: PostgresClient = Depends(get_data_client),
):
    return await mark_notification_read(sb=sb, access_token=session.access_token, notification_id=notification_id)
