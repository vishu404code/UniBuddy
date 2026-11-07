from uuid import UUID

from app.schemas.auth import CurrentUser

CROSS_CAMPUS_ROLES = frozenset({"management"})


def can_access_campus(user: CurrentUser, campus_id: UUID) -> bool:
    """Campus scoping for tickets, queues and campus-level administration.

    Documents and student-facing announcements are never filtered by this.
    Management sees every campus for reporting. Other roles see only their own.
    """
    if user.role in CROSS_CAMPUS_ROLES:
        return True
    return user.campus_id is not None and user.campus_id == campus_id
