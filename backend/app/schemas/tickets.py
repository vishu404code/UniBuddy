from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class TicketOut(BaseModel):
    id: UUID
    ticket_number: str
    subject: str
    question: str
    description: str | None
    priority: Literal["low", "medium", "high"]
    status: Literal["submitted", "assigned", "in_progress", "resolved"]
    campus_id: UUID
    department_id: UUID
    student_id: UUID
    assigned_faculty_id: UUID | None
    source_message_id: UUID | None
    created_at: datetime
    updated_at: datetime


class TicketEventOut(BaseModel):
    id: UUID
    event_type: Literal["status_change", "reply", "assignment"]
    note: str | None
    actor_id: UUID | None
    created_at: datetime


class TicketDetailOut(BaseModel):
    ticket: TicketOut
    events: list[TicketEventOut]


class TicketUpdateRequest(BaseModel):
    status: Literal["assigned", "in_progress", "resolved"] | None = None
    reply: str | None = Field(default=None, min_length=1, max_length=4000)
    take_ticket: bool = False

    @model_validator(mode="after")
    def at_least_one_change(self):
        if self.status is None and self.reply is None and not self.take_ticket:
            raise ValueError("Provide a status, a reply, or take_ticket")
        return self
