from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.announcements import AnnouncementCreate, AnnouncementOut
from app.schemas.common import Page
from app.services.announcements import create_announcement
from app.services.documents import attach_course_names, batch_filter, course_filter, text_filter
from app.services.providers import get_data_client
from app.services.postgres_client import PostgresClient

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
    course_id: Annotated[str | None, Query(max_length=40)] = None,
    academic_year: Annotated[str | None, Query(max_length=40)] = None,
    batch_year: Annotated[str | None, Query(max_length=12)] = None,
    section: Annotated[str | None, Query(max_length=12)] = None,
    created_from: datetime | None = None,
    created_before: datetime | None = None,
    sb: PostgresClient = Depends(get_data_client),
):
    """Announcements the caller may see. Filters narrow the results; they never widen access.
    A filter value of "unspecified" selects records where that field is not recorded."""
    filters = {"order": "created_at.desc"}
    if audience:
        filters["audience"] = f"eq.{audience}"
    if scope:
        filters["scope"] = f"eq.{scope}"
    if campus_id:
        filters["campus_id"] = f"eq.{campus_id}"
    if is_important is not None:
        filters["is_important"] = f"eq.{'true' if is_important else 'false'}"
    if course_id is not None:
        filters["course_id"] = course_filter(course_id)
    if academic_year is not None:
        filters["academic_year"] = text_filter(academic_year, 20)
    if batch_year is not None:
        filters["batch_year"] = batch_filter(batch_year)
    if section is not None:
        filters["section"] = text_filter(section, 10)
    if created_from is not None:
        filters["created_at"] = f"gte.{created_from.isoformat()}"
    if created_before is not None:
        filters["created_at~before"] = f"lt.{created_before.isoformat()}"
    rows, total = await sb.select_page_as_user(
        session.access_token, "announcements", {"select": "*", **filters}, limit, offset
    )
    await attach_course_names(sb, session.access_token, rows)
    return Page[AnnouncementOut](items=rows, total=total, limit=limit, offset=offset)


@router.post("", response_model=AnnouncementOut, status_code=201)
async def publish_announcement(
    body: AnnouncementCreate,
    session: Annotated[CurrentSession, Depends(session_with_roles("faculty", "authority"))],
    sb: PostgresClient = Depends(get_data_client),
):
    return await create_announcement(sb=sb, user=session.user, body=body)
