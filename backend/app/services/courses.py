"""Courses are a per-campus list. Authority manages it; Faculty and Authority may only select
active courses. A course that any document, announcement or student profile refers to is
deactivated, never hard-deleted, so existing records keep their meaning."""

from typing import Any
from uuid import UUID, uuid4

from app.schemas.auth import CurrentUser
from app.services.documents import DocumentConflict, DocumentError, DocumentForbidden, DocumentNotFound
from app.services.errors import DataServiceError
from app.services.postgres_client import PostgresClient

MAX_COURSE_NAME_LENGTH = 80
# Tables that point at a course. Any row here means the course is in use.
COURSE_REFERENCES = (
    ("documents", "course_id"),
    ("announcements", "course_id"),
    ("profiles", "course_id"),
)


def _require_authority(user: CurrentUser) -> None:
    if user.role != "authority":
        raise DocumentForbidden("Only authority can manage the course list")
    if user.campus_id is None:
        raise DocumentForbidden("Your account has no campus assigned")


def clean_course_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned or len(cleaned) > MAX_COURSE_NAME_LENGTH:
        raise DocumentError(f"Course name must be 1 to {MAX_COURSE_NAME_LENGTH} characters")
    return cleaned


async def list_courses(sb: PostgresClient, user: CurrentUser, *, include_inactive: bool) -> list[dict[str, Any]]:
    if user.campus_id is None:
        return []
    params = {
        "select": "id,name,active,created_at",
        "campus_id": f"eq.{user.campus_id}",
        "order": "name.asc",
    }
    if not include_inactive:
        params["active"] = "eq.true"
    return await sb.select_service("courses", params)


async def require_active_course(sb: PostgresClient, campus_id: UUID | None, course_id: UUID) -> None:
    """Selecting a course is allowed for any staff member on the same campus, but only when it is active."""
    if campus_id is None:
        raise DocumentForbidden("Your account has no campus assigned")
    rows = await sb.select_service(
        "courses",
        {"select": "id,active", "id": f"eq.{course_id}", "campus_id": f"eq.{campus_id}"},
    )
    if not rows or not rows[0]["active"]:
        raise DocumentError("Choose an active course from your campus")


async def _load_campus_course(sb: PostgresClient, user: CurrentUser, course_id: UUID) -> dict[str, Any]:
    rows = await sb.select_service(
        "courses",
        {"select": "*", "id": f"eq.{course_id}", "campus_id": f"eq.{user.campus_id}"},
    )
    if not rows:
        raise DocumentNotFound("Course not found")
    return rows[0]


async def _ensure_name_free(sb: PostgresClient, user: CurrentUser, name: str, except_id: UUID | None) -> None:
    existing = await sb.select_service(
        "courses", {"select": "id,name", "campus_id": f"eq.{user.campus_id}"}
    )
    for row in existing:
        same_name = row["name"].strip().lower() == name.lower()
        if same_name and str(row["id"]) != str(except_id or ""):
            raise DocumentConflict("A course with this name already exists on your campus")


async def create_course(sb: PostgresClient, user: CurrentUser, name: str) -> dict[str, Any]:
    _require_authority(user)
    cleaned = clean_course_name(name)
    await _ensure_name_free(sb, user, cleaned, None)
    course_id = uuid4()
    try:
        await sb.insert_service(
            "courses",
            [{
                "id": str(course_id),
                "campus_id": str(user.campus_id),
                "name": cleaned,
                "active": True,
                "created_by": str(user.id),
            }],
        )
    except DataServiceError as exc:
        if exc.status_code == 409:
            raise DocumentConflict("A course with this name already exists on your campus") from exc
        raise
    rows = await sb.select_service("courses", {"select": "*", "id": f"eq.{course_id}"})
    return rows[0]


async def update_course(
    sb: PostgresClient,
    user: CurrentUser,
    course_id: UUID,
    *,
    name: str | None,
    active: bool | None,
) -> dict[str, Any]:
    _require_authority(user)
    course = await _load_campus_course(sb, user, course_id)
    values: dict[str, Any] = {}
    if name is not None:
        cleaned = clean_course_name(name)
        await _ensure_name_free(sb, user, cleaned, course_id)
        values["name"] = cleaned
    if active is not None:
        values["active"] = active
    if not values:
        return course
    try:
        await sb.update_service("courses", {"id": f"eq.{course_id}"}, values)
    except DataServiceError as exc:
        if exc.status_code == 409:
            raise DocumentConflict("A course with this name already exists on your campus") from exc
        raise
    rows = await sb.select_service("courses", {"select": "*", "id": f"eq.{course_id}"})
    return rows[0]


async def _is_referenced(sb: PostgresClient, course_id: UUID) -> bool:
    for table, column in COURSE_REFERENCES:
        rows = await sb.select_service(table, {"select": "id", column: f"eq.{course_id}", "limit": "1"})
        if rows:
            return True
    return False


async def remove_course(sb: PostgresClient, user: CurrentUser, course_id: UUID) -> dict[str, Any]:
    """Deletes an unused course. A course in use is deactivated instead, so records keep their course."""
    _require_authority(user)
    await _load_campus_course(sb, user, course_id)
    if not await _is_referenced(sb, course_id):
        try:
            await sb.delete_service("courses", {"id": f"eq.{course_id}"})
            return {"action": "deleted", "id": str(course_id)}
        except DataServiceError:
            # A reference was added between the check and the delete. Deactivate instead.
            pass
    await sb.update_service("courses", {"id": f"eq.{course_id}"}, {"active": False})
    return {"action": "deactivated", "id": str(course_id)}
