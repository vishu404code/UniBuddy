from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: UUID
    text: str
    ticket_id: UUID | None
    is_read: bool
    created_at: datetime
