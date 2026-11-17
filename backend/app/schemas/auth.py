from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["student", "faculty", "authority", "management", "super_admin"]


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
    cross_campus_record_access: bool = False


class GoogleTokenIn(BaseModel):
    """A Google ID token from the sign-in button. Nothing else is accepted from the client."""

    model_config = ConfigDict(extra="forbid")

    id_token: str = Field(min_length=20, max_length=4096)


class SessionOut(BaseModel):
    access_token: str
    token_type: str = "bearer"

