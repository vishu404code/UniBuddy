from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Visibility = Literal["public_students", "staff_only"]
Scope = Literal["campus", "university_wide"]
ItemType = Literal["file", "text_content"]
PublicationStatus = Literal["draft", "published", "archived"]
ProcessingStatus = Literal["pending", "processing", "ready", "failed"]


class DocumentOut(BaseModel):
    id: UUID
    title: str
    original_filename: str | None = None
    item_type: ItemType = "file"
    category: str | None = "General"
    description: str | None = None
    raw_content: str | None = None
    visibility: Visibility = "public_students"
    scope: Scope = "campus"
    publication_status: PublicationStatus = "draft"
    processing_status: ProcessingStatus = "pending"
    processing_note: str | None = None
    page_count: int | None = None
    campus_id: UUID | None = None
    department_id: UUID | None = None
    effective_date: str | None = None
    expiry_date: str | None = None
    tags: list[str] = Field(default_factory=list)
    batch_year: int | None = None
    course: str | None = None
    course_id: str | None = None
    section: str | None = None
    replaces_document_id: UUID | None = None
    created_at: datetime


class TextContentCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    category: str = "General"
    description: str | None = None
    department_id: UUID | None = None
    scope: Scope = "campus"
    visibility: Visibility = "public_students"
    publication_status: Literal["draft", "published"] = "draft"
    effective_date: str | None = None
    expiry_date: str | None = None
    tags: list[str] = Field(default_factory=list)


class TextContentUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content: str | None = None
    category: str | None = None
    description: str | None = None
    department_id: UUID | None = None
    scope: Scope | None = None
    visibility: Visibility | None = None
    publication_status: PublicationStatus | None = None
    effective_date: str | None = None
    expiry_date: str | None = None
    tags: list[str] | None = None
    batch_year: int | None = None
    course: str | None = None
    course_id: str | None = None
    section: str | None = None


class DocumentUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    category: str | None = None
    description: str | None = None
    department_id: UUID | None = None
    scope: Scope | None = None
    visibility: Visibility | None = None
    publication_status: PublicationStatus | None = None
    effective_date: str | None = None
    expiry_date: str | None = None
    tags: list[str] | None = None
    batch_year: int | None = None
    course: str | None = None
    course_id: str | None = None
    section: str | None = None


class KnowledgeStatsOut(BaseModel):
    total_items: int = 0
    total_documents: int = 0
    total_text_content: int = 0
    published_count: int = 0
    draft_count: int = 0
    archived_count: int = 0
    processing_count: int = 0
    failed_count: int = 0
