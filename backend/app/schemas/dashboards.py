from datetime import date, datetime
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


class DailyCount(BaseModel):
    day: date
    count: int


class GeminiUsage(BaseModel):
    """Recorded Gemini answer calls. Counts are null when Gemini did not return them.

    Usage before the feature was deployed was never recorded, so it is not in these numbers.
    """

    operation: str
    first_recorded_at: datetime | None
    last_recorded_at: datetime | None
    rows_recorded: int
    requests: int
    rows_with_input_tokens: int
    rows_with_output_tokens: int
    input_tokens: int | None
    output_tokens: int | None
    models: list[str]


class ManagementAnalytics(BaseModel):
    """Aggregate counts only. No names, emails, question text or chat contents."""

    questions_total: int
    questions_by_day: list[DailyCount]
    tickets_by_day: list[DailyCount]
    gemini: GeminiUsage
    ticket_totals: ManagementStats
    generated_at: datetime
