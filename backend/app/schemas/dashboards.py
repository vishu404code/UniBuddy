from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class StudentDashboard(BaseModel):
    total_questions: int
    total_tickets: int
    tickets_by_status: dict[str, int]
    generated_at: datetime


class StaffDepartmentStats(BaseModel):
    department_id: UUID
    name: str
    total: int
    resolved: int


class StaffDashboard(BaseModel):
    """Counts over the tickets and documents the caller can see under RLS."""

    open_tickets: int
    resolved_tickets: int
    tickets_by_status: dict[str, int]
    unassigned_queue: int
    assigned_to_me: int
    avg_first_response_hours: float | None
    by_department: list[StaffDepartmentStats]
    drafts_visible: int
    published_visible: int


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
