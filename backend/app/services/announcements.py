from typing import Any
from uuid import uuid4

from app.schemas.announcements import AnnouncementCreate
from app.schemas.auth import CurrentUser
from app.services.documents import DocumentForbidden
from app.services.postgres_client import PostgresClient


async def create_announcement(*, sb: PostgresClient, user: CurrentUser, body: AnnouncementCreate) -> dict[str, Any]:
    if body.scope == "university_wide" and user.role != "authority":
        raise DocumentForbidden("Only authority can publish university-wide announcements")
    if body.scope == "campus" and user.campus_id is None:
        raise DocumentForbidden("Your account has no campus assigned")

    row = {
        "id": str(uuid4()),
        "audience": body.audience,
        "scope": body.scope,
        "campus_id": str(user.campus_id) if body.scope == "campus" else None,
        "department_id": None,
        "category": body.category,
        "title": body.title.strip(),
        "body": body.body.strip(),
        "is_important": body.is_important,
        "published_by": str(user.id),
    }
    await sb.insert_service("announcements", [row])
    rows = await sb.select_service("announcements", {"select": "*", "id": f"eq.{row['id']}"})
    return rows[0]
