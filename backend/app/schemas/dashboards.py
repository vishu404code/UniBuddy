from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class StudentDashboard(BaseModel):
    total_questions: int
    total_tickets: int
    tickets_by_status: dict[str, int]
    generated_at: datetime


class GroupStats(BaseModel):
    id: UUID
    name: str
    total_tickets: int
    resolved_tickets: int
    resolution_rate: float | None
    avg_first_response_hours: float | None


class ManagementStats(BaseModel):
    total_tickets: int
    resolved_tickets: int
    resolution_rate: float | None
    avg_first_response_hours: float | None
    campuses: list[GroupStats]
    departments: list[GroupStats]
    generated_at: datetime
