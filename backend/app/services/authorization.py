from uuid import UUID

from app.schemas.auth import CurrentUser


def can_access_campus(user: CurrentUser, campus_id: UUID) -> bool:
    """Campus scoping for tickets, queues and campus-level administration.

    Documents and student-facing announcements are never filtered by this.
    Users see their own campus. Only an explicit all_campuses_access grant
    (management) lets them see other campuses.
    """
    if user.all_campuses_access:
        return True
    return user.campus_id is not None and user.campus_id == campus_id
