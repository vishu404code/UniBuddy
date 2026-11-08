from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

Visibility = Literal["public_students", "staff_only"]
Scope = Literal["campus", "university_wide"]


class DocumentOut(BaseModel):
    id: UUID
    title: str
    original_filename: str | None
    visibility: Visibility
    scope: Scope
    publication_status: Literal["draft", "published", "archived"]
    processing_status: Literal["pending", "processing", "ready", "failed"]
    page_count: int | None
    campus_id: UUID | None
    department_id: UUID | None
    created_at: datetime
