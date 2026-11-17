from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class FilterOptionOut(BaseModel):
    id: UUID
    kind: Literal["academic_year", "batch", "section"]
    value: str
    active: bool
    created_at: datetime | None = None


class FilterOptionCreate(BaseModel):
    kind: Literal["academic_year", "batch", "section"]
    value: str = Field(min_length=1, max_length=20)


class FilterOptionPatch(BaseModel):
    active: bool
