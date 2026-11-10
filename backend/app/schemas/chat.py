from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    conversation_id: UUID | None = None


class CitationOut(BaseModel):
    document_id: UUID
    title: str
    page: int | None


class AskResponse(BaseModel):
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    answer: str
    abstained: bool
    citations: list[CitationOut]
    escalation_available: bool


class ForwardRequest(BaseModel):
    # Optional. Without a department the ticket goes to the campus queue.
    department_id: UUID | None = None
    priority: Literal["low", "medium", "high"] = "medium"
    description: str | None = Field(default=None, max_length=2000)


class ForwardResponse(BaseModel):
    ticket_id: UUID
    ticket_number: str
    status: str


class ConversationOut(BaseModel):
    id: UUID
    title: str | None
    created_at: datetime


class MessageOut(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[dict[str, Any]]
    created_at: datetime
