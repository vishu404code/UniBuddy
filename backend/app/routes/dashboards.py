from typing import Annotated

from fastapi import APIRouter, Depends

from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.dashboards import (
    ManagementAnalytics,
    ManagementPlatformOverview,
    ManagementStats,
    StaffDashboard,
    StudentDashboard,
)
from app.services.dashboards import (
    management_analytics,
    management_platform_overview,
    management_stats,
    staff_dashboard,
    student_dashboard,
)
from app.services.providers import get_data_client
from app.services.postgres_client import PostgresClient

router = APIRouter(tags=["dashboards"])


@router.get("/dashboard/student", response_model=StudentDashboard)
async def student_stats(
    session: Annotated[CurrentSession, Depends(session_with_roles("student"))],
    sb: PostgresClient = Depends(get_data_client),
):
    return await student_dashboard(sb, session.access_token)


@router.get("/dashboard/staff", response_model=StaffDashboard)
async def staff_overview(
    session: Annotated[CurrentSession, Depends(session_with_roles("faculty", "authority"))],
    sb: PostgresClient = Depends(get_data_client),
):
    return await staff_dashboard(sb, session.access_token)


@router.get("/management/stats", response_model=ManagementStats)
async def management_overview(
    _session: Annotated[CurrentSession, Depends(session_with_roles("management", "super_admin"))],
    sb: PostgresClient = Depends(get_data_client),
):
    return await management_stats(sb)


@router.get("/management/analytics", response_model=ManagementAnalytics)
async def management_analytics_overview(
    _session: Annotated[CurrentSession, Depends(session_with_roles("management", "super_admin"))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Read-only, aggregate. Management only: the role comes from the database profile."""
    return await management_analytics(sb)


@router.get("/management/overview", response_model=ManagementPlatformOverview)
async def management_platform_full_overview(
    _session: Annotated[CurrentSession, Depends(session_with_roles("management", "super_admin"))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Comprehensive real-time platform metrics across students, faculty, clubs, documents, announcements, and tickets."""
    return await management_platform_overview(sb)
