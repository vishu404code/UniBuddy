from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.announcements import AnnouncementCreate, AnnouncementOut
from app.schemas.common import Page
from app.services.announcements import create_announcement
from app.services.providers import get_data_client
from app.services.postgres_client import PostgresClient

router = APIRouter(prefix="/announcements", tags=["announcements"])


def _matches_student_target(row: dict, user_meta: dict) -> bool:
    target_batch = row.get("batch_year")
    target_course = (row.get("course") or row.get("course_id") or "").strip().lower()
    target_section = (row.get("section") or "").strip().lower()

    if target_batch is not None and str(target_batch).strip() != "":
        student_batch = str(user_meta.get("batch_year") or user_meta.get("batch") or "").strip()
        if student_batch and student_batch != str(target_batch).strip():
            return False

    if target_course and target_course != "all":
        student_course = str(user_meta.get("course") or user_meta.get("course_id") or "").strip().lower()
        if student_course:
            sc = student_course.replace("b.tech ", "").replace("&", "and").strip()
            tc = target_course.replace("b.tech ", "").replace("&", "and").strip()
            if tc != sc and tc not in sc and sc not in tc:
                return False

    if target_section and target_section != "all":
        student_section = str(user_meta.get("section") or "").strip().lower()
        if student_section and student_section != target_section:
            return False

    return True


@router.get("", response_model=Page[AnnouncementOut])
async def list_announcements(
    session: Annotated[CurrentSession, Depends(session_with_roles("student", "faculty", "authority", "management"))],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    audience: Literal["all_students", "staff_only"] | None = None,
    scope: Literal["campus", "university_wide"] | None = None,
    campus_id: UUID | None = None,
    is_important: bool | None = None,
    sb: PostgresClient = Depends(get_data_client),
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
    if session.user.role == "student":
        user_meta = dict(getattr(session.user, "metadata", None) or {})
        if user_meta:
            before_len = len(rows)
            rows = [r for r in rows if _matches_student_target(r, user_meta)]
            if len(rows) < before_len:
                total = max(0, total - (before_len - len(rows)))
    return Page[AnnouncementOut](items=rows, total=total, limit=limit, offset=offset)


@router.post("", response_model=AnnouncementOut, status_code=201)
async def publish_announcement(
    body: AnnouncementCreate,
    session: Annotated[CurrentSession, Depends(session_with_roles("faculty", "authority"))],
    sb: PostgresClient = Depends(get_data_client),
):
    return await create_announcement(sb=sb, user=session.user, body=body)
