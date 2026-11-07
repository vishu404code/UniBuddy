from typing import Literal
from uuid import UUID

from pydantic import BaseModel

Role = Literal["student", "faculty", "authority", "management"]


class CurrentUser(BaseModel):
    """The authenticated user as seen by the backend.

    Built from the verified token's `sub` plus the `profiles` row. Role, campus
    and cross-campus access always come from the profiles table, never from
    token claims.
    """

    id: UUID
    email: str
    full_name: str | None
    role: Role
    campus_id: UUID | None
    department_id: UUID | None
    all_campuses_access: bool = False
