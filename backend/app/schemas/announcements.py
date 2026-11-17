from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

MAX_RECIPIENTS = 200


class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    category: str | None = Field(default=None, max_length=50)
    is_important: bool = False
    audience: Literal["all_students", "staff_only"] = "all_students"
    scope: Literal["campus", "university_wide"] = "campus"
    # Optional targeting for all_students announcements. Empty means every student.
    academic_year: str | None = Field(default=None, max_length=20)
    batch_year: int | None = Field(default=None, ge=2000, le=2100)
    section: str | None = Field(default=None, max_length=10)
    course_id: UUID | None = None
    # Students picked by name. They receive the announcement even when no filter matches them.
    person_ids: list[UUID] = Field(default_factory=list, max_length=MAX_RECIPIENTS)

    @model_validator(mode="after")
    def targets_only_for_students(self):
        has_target = (
            self.academic_year is not None or self.batch_year is not None or self.section is not None
            or self.course_id is not None or bool(self.person_ids)
        )
        if has_target and self.audience != "all_students":
            raise ValueError("Targeting applies only to announcements for students")
        return self


class AnnouncementOut(BaseModel):
    id: UUID
    title: str
    body: str
    category: str | None
    is_important: bool
    audience: Literal["all_students", "staff_only"]
    scope: Literal["campus", "university_wide"]
    campus_id: UUID | None
    academic_year: str | None = None
    batch_year: int | None = None
    section: str | None = None
    course_id: UUID | None = None
    created_at: datetime
