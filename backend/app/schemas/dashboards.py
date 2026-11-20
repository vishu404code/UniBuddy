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


class StudentBreakdown(BaseModel):
    batch_year: dict[str, int]
    course: dict[str, int]
    section: dict[str, int]


class StudentOverview(BaseModel):
    total: int
    active: int
    inactive: int
    breakdown: StudentBreakdown
    sample: list[dict[str, Any]] = []


class FacultyOverview(BaseModel):
    total: int
    active: int
    by_department: dict[str, int]
    sample: list[dict[str, Any]] = []


class ClubOverview(BaseModel):
    total_initiatives: int
    active_clubs: list[str]
    notes: str
    initiatives: list[dict[str, Any]] = []


class DocumentOverview(BaseModel):
    total: int
    by_category: dict[str, int]
    by_status: dict[str, int]
    recent: list[dict[str, Any]] = []


class AnnouncementOverview(BaseModel):
    total: int
    published: int
    by_category: dict[str, int]
    by_target: dict[str, int]
    recent: list[dict[str, Any]] = []


class TicketOverview(BaseModel):
    total: int
    by_status: dict[str, int]
    resolution_rate: float | None
    recent: list[dict[str, Any]] = []


class PlatformActivityOverview(BaseModel):
    total_users: int
    by_role: dict[str, int]
    recent_events: list[dict[str, Any]] = []


class ManagementPlatformOverview(BaseModel):
    students: StudentOverview
    faculty: FacultyOverview
    clubs: ClubOverview
    documents: DocumentOverview
    announcements: AnnouncementOverview
    tickets: TicketOverview
    platform: PlatformActivityOverview
    generated_at: datetime
