from typing import Annotated

from fastapi import APIRouter, Depends

from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.provisioning import DepartmentOut
from app.services.providers import get_data_client
from app.services.postgres_client import PostgresClient

router = APIRouter(tags=["departments"])


@router.get("/departments", response_model=list[DepartmentOut])
async def campus_departments(
    session: Annotated[CurrentSession, Depends(session_with_roles("student", "faculty", "authority"))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Departments on the caller's own campus. The campus comes from the profile, never from the client."""
    if session.user.campus_id is None:
        return []
    return await sb.select_service(
        "departments",
        {"select": "id,name", "campus_id": f"eq.{session.user.campus_id}", "order": "name.asc"},
    )
