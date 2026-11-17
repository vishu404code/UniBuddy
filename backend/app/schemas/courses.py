from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class CourseOut(BaseModel):
    id: UUID
    name: str
    active: bool
    created_at: datetime | None = None


class CourseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class CoursePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    active: bool | None = None

    @model_validator(mode="after")
    def at_least_one_change(self):
        if self.name is None and self.active is None:
            raise ValueError("Provide a name or active")
        return self
