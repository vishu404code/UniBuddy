from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.middleware.auth import CurrentSession, session_with_roles
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
            "select": "id,full_name,email",
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
    return [StudentPick(id=str(r["id"]), full_name=r.get("full_name"), email=r["email"]) for r in matches[:RESULT_LIMIT]]
