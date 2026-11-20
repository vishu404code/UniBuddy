from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    category: str | None = Field(default=None, max_length=50)
    is_important: bool = False
    audience: Literal["all_students", "staff_only"] = "all_students"
    scope: Literal["campus", "university_wide"] = "campus"
    batch_year: int | None = None
    course: str | None = None
    course_id: str | None = None
    section: str | None = None


class AnnouncementOut(BaseModel):
    id: UUID
    title: str
    body: str
    category: str | None
    is_important: bool
    audience: Literal["all_students", "staff_only"]
    scope: Literal["campus", "university_wide"]
    campus_id: UUID | None
    batch_year: int | None = None
    course: str | None = None
    course_id: str | None = None
    section: str | None = None
    created_at: datetime
