from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.middleware.auth import CurrentSession, session_with_roles
from app.services.academics import assign_student_academics
from app.services.postgres_client import PostgresClient
from app.services.providers import get_data_client

router = APIRouter(prefix="/people", tags=["people"])
# How many campus students are read before the name filter is applied. Campus sizes are far below this.
SEARCH_SCAN_LIMIT = 500
RESULT_LIMIT = 20


class StudentPick(BaseModel):
    id: str
    full_name: str | None
    email: str
    batch_year: int | None = None
    section: str | None = None
    course_id: str | None = None


class AcademicsIn(BaseModel):
    """Null clears a field. Only active campus options and courses are accepted."""

    batch_year: int | None = Field(default=None, ge=2000, le=2100)
    section: str | None = Field(default=None, max_length=10)
    course_id: UUID | None = None


class AcademicsOut(BaseModel):
    batch_year: int | None
    section: str | None
    course_id: str | None


@router.get("/students", response_model=list[StudentPick])
async def find_students(
    session: Annotated[CurrentSession, Depends(session_with_roles("faculty", "authority"))],
    q: Annotated[str, Query(max_length=80)] = "",
    sb: PostgresClient = Depends(get_data_client),
):
    """Students on the caller's own campus, for choosing who an announcement is for. Read through the
    caller's own access (RLS), so only the profiles that role may already read are returned."""
    if session.user.campus_id is None:
        return []
    rows = await sb.select_as_user(
        session.access_token,
        "profiles",
        {
            "select": "id,full_name,email,batch_year,section,course_id",
            "role": "eq.student",
            "campus_id": f"eq.{session.user.campus_id}",
            "order": "full_name.asc",
            "limit": str(SEARCH_SCAN_LIMIT),
        },
    )
    needle = q.strip().lower()
    matches = [
        r for r in rows
        if not needle or needle in (r.get("full_name") or "").lower() or needle in (r.get("email") or "").lower()
    ]
    return [
        StudentPick(
            id=str(r["id"]), full_name=r.get("full_name"), email=r["email"],
            batch_year=r.get("batch_year"), section=r.get("section"),
            course_id=str(r["course_id"]) if r.get("course_id") else None,
        )
        for r in matches[:RESULT_LIMIT]
    ]


@router.patch("/students/{student_id}/academics", response_model=AcademicsOut)
async def set_student_academics(
    student_id: UUID,
    body: AcademicsIn,
    session: Annotated[CurrentSession, Depends(session_with_roles("authority"))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Authority only. Faculty may view these values; students cannot set their own."""
    result = await assign_student_academics(
        sb=sb, actor=session.user, access_token=session.access_token, student_id=student_id,
        batch_year=body.batch_year, section=body.section, course_id=body.course_id,
    )
    return AcademicsOut(batch_year=result.get("batch_year"), section=result.get("section"),
                        course_id=str(result["course_id"]) if result.get("course_id") else None)
