from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.provisioning import EMAIL_PATTERN


class RegistrationRequestIn(BaseModel):
    """Public intake. Only the applicant's own email and name. No role, campus or owner."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    full_name: str = Field(min_length=2, max_length=120)

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
            raise ValueError("Enter your full name")
        return value


class RegistrationReceiptOut(BaseModel):
    status: str
    message: str
