from typing import Annotated

from fastapi import APIRouter, Depends

from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.dashboards import ManagementStats, StaffDashboard, StudentDashboard
from app.services.dashboards import management_stats, staff_dashboard, student_dashboard
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
    _session: Annotated[CurrentSession, Depends(session_with_roles("management"))],
    sb: PostgresClient = Depends(get_data_client),
):
    return await management_stats(sb)
