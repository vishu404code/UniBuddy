import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ProvisionUserRequest(BaseModel):
    """The only fields an authority may send. Role, campus, owner and cross-campus
    access are never accepted: extra fields are rejected, and the role comes from the
    endpoint, the campus from the actor's profile."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    full_name: str = Field(min_length=2, max_length=120)
    department_id: UUID | None = None

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL_PATTERN.match(value):
            raise ValueError("Enter a valid email address")
        return value

    @field_validator("full_name")
    @classmethod
    def trimmed_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Enter a full name")
        return value


class ProvisionedUserOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    campus_id: UUID
    department_id: UUID | None
    status: str
