from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    conversation_id: UUID | None = None
    # Explicit opt-in: answer from the Student's own saved summaries of earlier chats. Off by default. It only takes
    # effect when the memory feature flag is on, and it never uses official documents or a model.
    recall_own_chats: bool = False


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


class MemoryOut(BaseModel):
    id: UUID
    summary: str
    importance: Literal["normal", "important", "pinned"]
    use_count: int
    corrected_at: datetime | None = None
    last_message_at: datetime


class MemoryPatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=1500)
    importance: Literal["normal", "important", "pinned"] | None = None

    @model_validator(mode="after")
    def at_least_one_change(self):
        if self.text is None and self.importance is None:
            raise ValueError("Provide text or importance")
        return self


class AnswerStyleIn(BaseModel):
    # Codes only. The text each code stands for is fixed on the server (ANSWER_STYLES in app.ai.rag).
    style: Literal["concise", "plain_language"]
