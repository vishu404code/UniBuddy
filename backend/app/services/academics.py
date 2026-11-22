"""Authority assigns a student's batch, section and course. Students and faculty cannot.

Values are checked against the campus's ACTIVE options and courses, both here and in the database (migration
20261122140000). Nothing is inferred or bulk-filled: a field the Authority leaves empty stays unset.
"""

from uuid import UUID

from app.schemas.auth import CurrentUser
from app.services.documents import DocumentError, DocumentForbidden, DocumentNotFound
from app.services.errors import DataServiceError
from app.services.postgres_client import PostgresClient

REASONS = {
    "batch_not_active": "That batch is not an active option for your campus.",
    "section_not_active": "That section is not an active option for your campus.",
    "course_not_active": "That course is not an active course on your campus.",
    "student_has_no_campus": "This student has no campus, so their details cannot be set.",
    "not_authorized": "Only Authority of this campus can change student academic details.",
}


async def assign_student_academics(
    *,
    sb: PostgresClient,
    actor: CurrentUser,
    access_token: str,
    student_id: UUID,
    batch_year: int | None,
    section: str | None,
    course_id: UUID | None,
) -> dict:
    if actor.role != "authority" or actor.campus_id is None:
        raise DocumentForbidden("Only Authority can change student academic details.")
    section = section.strip() if section else None

    # The student must be visible to this Authority under row-level security, and on the same campus.
    rows = await sb.select_as_user(
        access_token, "profiles", {"select": "id,role,campus_id", "id": f"eq.{student_id}"}
    )
    if not rows or rows[0]["role"] != "student" or str(rows[0]["campus_id"]) != str(actor.campus_id):
        raise DocumentNotFound("Student not found on your campus.")

    try:
        return await sb.rpc_service("assign_student_academics", {
            "p_student": str(student_id),
            "p_actor": str(actor.id),
            "p_batch_year": batch_year,
            "p_section": section,
            "p_course_id": str(course_id) if course_id else None,
        })
    except DataServiceError as exc:
        reason = str(exc.detail)
        for key, message in REASONS.items():
            if key in reason:
                raise DocumentError(message) from exc
        raise
