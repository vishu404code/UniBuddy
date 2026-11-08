import re
from datetime import datetime
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


class SuperAdminInviteRequest(BaseModel):
    """Super Admin only. The campus is an administrative choice, validated in the database.
    The invitee never chooses it, and the role comes from the endpoint, not the body."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    full_name: str = Field(min_length=2, max_length=120)
    campus_id: UUID | None = None

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
    campus_id: UUID | None
    department_id: UUID | None
    status: str


class RegistrationOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    requested_at: datetime


class RejectRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class CampusOut(BaseModel):
    id: UUID
    name: str
    code: str


class DepartmentOut(BaseModel):
    id: UUID
    name: str


class AccountOut(BaseModel):
    """Account fields only. Academic records are never part of this shape."""

    id: UUID
    email: str
    full_name: str | None
    role: str
    campus_id: UUID | None
    campus_name: str | None
    created_at: datetime
