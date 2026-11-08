from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.announcements import AnnouncementCreate, AnnouncementOut
from app.schemas.common import Page
from app.services.announcements import create_announcement
from app.services.providers import get_supabase_client
from app.services.supabase_client import SupabaseClient

router = APIRouter(prefix="/announcements", tags=["announcements"])


@router.get("", response_model=Page[AnnouncementOut])
async def list_announcements(
    session: Annotated[CurrentSession, Depends(session_with_roles("student", "faculty", "authority", "management"))],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    audience: Literal["all_students", "staff_only"] | None = None,
    scope: Literal["campus", "university_wide"] | None = None,
    campus_id: UUID | None = None,
    is_important: bool | None = None,
    sb: SupabaseClient = Depends(get_supabase_client),
):
    filters = {"order": "created_at.desc"}
    if audience:
        filters["audience"] = f"eq.{audience}"
    if scope:
        filters["scope"] = f"eq.{scope}"
    if campus_id:
        filters["campus_id"] = f"eq.{campus_id}"
    if is_important is not None:
        filters["is_important"] = f"eq.{'true' if is_important else 'false'}"
    rows, total = await sb.select_page_as_user(
        session.access_token, "announcements", {"select": "*", **filters}, limit, offset
    )
    return Page[AnnouncementOut](items=rows, total=total, limit=limit, offset=offset)


@router.post("", response_model=AnnouncementOut, status_code=201)
async def publish_announcement(
    body: AnnouncementCreate,
    session: Annotated[CurrentSession, Depends(session_with_roles("faculty", "authority"))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    return await create_announcement(sb=sb, user=session.user, body=body)
