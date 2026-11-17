from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.courses import CourseCreate, CourseOut, CoursePatch
from app.services.courses import create_course, list_courses, remove_course, update_course
from app.services.postgres_client import PostgresClient
from app.services.providers import get_data_client

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("", response_model=list[CourseOut])
async def courses_for_my_campus(
    session: Annotated[CurrentSession, Depends(session_with_roles("faculty", "authority"))],
    include_inactive: Annotated[bool, Query()] = False,
    sb: PostgresClient = Depends(get_data_client),
):
    """Courses on the caller's own campus. Faculty only see active courses; inactive ones are
    shown to Authority, who manages the list, when include_inactive is set."""
    include = include_inactive and session.user.role == "authority"
    return await list_courses(sb, session.user, include_inactive=include)


@router.post("", response_model=CourseOut, status_code=201)
async def add_course(
    body: CourseCreate,
    session: Annotated[CurrentSession, Depends(session_with_roles("authority"))],
    sb: PostgresClient = Depends(get_data_client),
):
    return await create_course(sb, session.user, body.name)


@router.patch("/{course_id}", response_model=CourseOut)
async def change_course(
    course_id: UUID,
    body: CoursePatch,
    session: Annotated[CurrentSession, Depends(session_with_roles("authority"))],
    sb: PostgresClient = Depends(get_data_client),
):
    return await update_course(sb, session.user, course_id, name=body.name, active=body.active)


@router.delete("/{course_id}")
async def delete_course(
    course_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles("authority"))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Deletes an unused course. A course that documents, announcements or students use is deactivated."""
    return await remove_course(sb, session.user, course_id)
