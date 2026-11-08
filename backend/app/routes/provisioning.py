from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import settings
from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.provisioning import ProvisionedUserOut, ProvisionUserRequest
from app.services.provisioning import provision_user
from app.services.providers import get_auth_admin_client, get_supabase_client
from app.services.auth_admin import AuthAdminClient
from app.services.supabase_client import SupabaseClient

router = APIRouter(prefix="/provisioning", tags=["provisioning"])


@router.post("/students", response_model=ProvisionedUserOut, status_code=201)
async def provision_student(
    body: ProvisionUserRequest,
    session: Annotated[CurrentSession, Depends(session_with_roles("authority"))],
    sb: SupabaseClient = Depends(get_supabase_client),
    auth_admin: AuthAdminClient = Depends(get_auth_admin_client),
):
    """Invites a student into the authority's own campus. Sends a real invitation email."""
    created = await provision_user(
        sb=sb, auth_admin=auth_admin, actor=session.user,
        email=body.email, full_name=body.full_name, role="student", department_id=body.department_id,
        allowed_domains=settings.provisioning_allowed_domains_set,
    )
    return ProvisionedUserOut(**created)


@router.post("/faculty", response_model=ProvisionedUserOut, status_code=201)
async def provision_faculty(
    body: ProvisionUserRequest,
    session: Annotated[CurrentSession, Depends(session_with_roles("authority"))],
    sb: SupabaseClient = Depends(get_supabase_client),
    auth_admin: AuthAdminClient = Depends(get_auth_admin_client),
):
    """Invites a faculty member into the authority's own campus. Department is required."""
    created = await provision_user(
        sb=sb, auth_admin=auth_admin, actor=session.user,
        email=body.email, full_name=body.full_name, role="faculty", department_id=body.department_id,
        allowed_domains=settings.provisioning_allowed_domains_set,
    )
    return ProvisionedUserOut(**created)
