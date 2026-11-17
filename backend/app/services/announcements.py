from typing import Any
from uuid import UUID, uuid4

from app.schemas.announcements import AnnouncementCreate
from app.schemas.auth import CurrentUser
from app.services.documents import DocumentError, DocumentForbidden, require_active_option
from app.services.postgres_client import PostgresClient


async def _check_course(sb: PostgresClient, campus_id: UUID, course_id: UUID) -> None:
    rows = await sb.select_service(
        "courses",
        {"select": "id,active", "id": f"eq.{course_id}", "campus_id": f"eq.{campus_id}"},
    )
    if not rows or not rows[0]["active"]:
        raise DocumentError("Choose an active course from your campus")


async def _check_people(sb: PostgresClient, campus_id: UUID, person_ids: list[UUID]) -> None:
    """Selected people must be students on the publisher's own campus."""
    wanted = {str(pid) for pid in person_ids}
    if not wanted:
        return
    rows = await sb.select_service(
        "profiles",
        {"select": "id,role,campus_id", "id": f"in.({','.join(sorted(wanted))})"},
    )
    found = {str(r["id"]): r for r in rows}
    for pid in wanted:
        row = found.get(pid)
        if row is None or row["role"] != "student" or str(row["campus_id"]) != str(campus_id):
            raise DocumentError("Selected people must be students on your campus")


async def create_announcement(*, sb: PostgresClient, user: CurrentUser, body: AnnouncementCreate) -> dict[str, Any]:
    if body.scope == "university_wide" and user.role != "authority":
        raise DocumentForbidden("Only authority can publish university-wide announcements")
    if body.scope == "campus" and user.campus_id is None:
        raise DocumentForbidden("Your account has no campus assigned")

    has_target = (
        body.academic_year is not None or body.batch_year is not None or body.section is not None
        or body.course_id is not None or bool(body.person_ids)
    )
    if has_target and user.campus_id is None:
        raise DocumentForbidden("Your account has no campus assigned")
    if body.course_id is not None:
        await _check_course(sb, user.campus_id, body.course_id)
    if has_target:
        # Year, batch and section are chosen from the campus's active options.
        if body.academic_year:
            await require_active_option(sb, user.campus_id, "academic_year", body.academic_year.strip())
        if body.batch_year is not None:
            await require_active_option(sb, user.campus_id, "batch", str(body.batch_year))
        if body.section:
            await require_active_option(sb, user.campus_id, "section", body.section.strip())
    person_ids = list(dict.fromkeys(body.person_ids))
    if person_ids:
        await _check_people(sb, user.campus_id, person_ids)

    announcement_id = uuid4()
    row = {
        "id": str(announcement_id),
        "audience": body.audience,
        "scope": body.scope,
        # Campus is kept for campus-scoped announcements and for course targets (a course belongs to one
        # campus). Visibility still follows the scope and the targets.
        "campus_id": str(user.campus_id) if (body.scope == "campus" or body.course_id is not None) and user.campus_id else None,
        "department_id": None,
        "category": body.category,
        "title": body.title.strip(),
        "body": body.body.strip(),
        "is_important": body.is_important,
        "published_by": str(user.id),
        "academic_year": body.academic_year.strip() if body.academic_year and body.academic_year.strip() else None,
        "batch_year": body.batch_year,
        "section": body.section.strip() if body.section and body.section.strip() else None,
        "course_id": str(body.course_id) if body.course_id else None,
    }
    await sb.insert_service("announcements", [row])
    if person_ids:
        try:
            await sb.insert_service(
                "announcement_recipients",
                [{"announcement_id": str(announcement_id), "profile_id": str(pid)} for pid in person_ids],
            )
        except Exception:
            # Without its recipients a targeted announcement would look untargeted and reach every
            # student, so remove it before reporting the failure.
            await sb.delete_service("announcements", {"id": f"eq.{announcement_id}"})
            raise
    rows = await sb.select_service("announcements", {"select": "*", "id": f"eq.{announcement_id}"})
    return rows[0]
