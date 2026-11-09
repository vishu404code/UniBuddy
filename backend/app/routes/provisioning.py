from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.config import settings
from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.provisioning import (
    CampusOut,
    DepartmentOut,
    ProvisionedUserOut,
    ProvisionUserRequest,
    RegistrationOut,
    RejectRegistrationRequest,
    SuperAdminInviteRequest,
)
from app.services.account_directory import AccountDirectory
from app.services.provisioning import provision_by_super_admin, provision_user
from app.services.providers import get_account_directory, get_data_client
from app.services.registration_review import (
    approve_registration,
    list_pending_registrations,
    reject_registration,
)
from app.services.postgres_client import PostgresClient

router = APIRouter(prefix="/provisioning", tags=["provisioning"])


@router.post("/students", response_model=ProvisionedUserOut, status_code=201)
async def provision_student(
    body: ProvisionUserRequest,
    session: Annotated[CurrentSession, Depends(session_with_roles("authority"))],
    sb: PostgresClient = Depends(get_data_client),
    accounts: AccountDirectory = Depends(get_account_directory),
):
    """Invites a student into the authority's own campus. Sends a real invitation email."""
    created = await provision_user(
        sb=sb, accounts=accounts, actor=session.user,
        email=body.email, full_name=body.full_name, role="student", department_id=body.department_id,
    )
    return ProvisionedUserOut(**created)


@router.post("/faculty", response_model=ProvisionedUserOut, status_code=201)
async def provision_faculty(
    body: ProvisionUserRequest,
    session: Annotated[CurrentSession, Depends(session_with_roles("authority"))],
    sb: PostgresClient = Depends(get_data_client),
    accounts: AccountDirectory = Depends(get_account_directory),
):
    """Invites a faculty member into the authority's own campus. Department is required."""
    created = await provision_user(
        sb=sb, accounts=accounts, actor=session.user,
        email=body.email, full_name=body.full_name, role="faculty", department_id=body.department_id,
    )
    return ProvisionedUserOut(**created)


@router.post("/authority", response_model=ProvisionedUserOut, status_code=201)
async def provision_authority(
    body: SuperAdminInviteRequest,
    session: Annotated[CurrentSession, Depends(session_with_roles("super_admin"))],
    sb: PostgresClient = Depends(get_data_client),
    accounts: AccountDirectory = Depends(get_account_directory),
):
    """Super Admin only. Invites an authority user to the campus Super Admin chooses. Sends a real email."""
    created = await provision_by_super_admin(
        sb=sb, accounts=accounts, actor=session.user, email=body.email, full_name=body.full_name,
        role="authority", campus_id=body.campus_id,
    )
    return ProvisionedUserOut(**created)


@router.post("/management", response_model=ProvisionedUserOut, status_code=201)
async def provision_management(
    body: SuperAdminInviteRequest,
    session: Annotated[CurrentSession, Depends(session_with_roles("super_admin"))],
    sb: PostgresClient = Depends(get_data_client),
    accounts: AccountDirectory = Depends(get_account_directory),
):
    """Super Admin only. Invites a management user. Management stays aggregate-only. Sends a real email."""
    created = await provision_by_super_admin(
        sb=sb, accounts=accounts, actor=session.user, email=body.email, full_name=body.full_name,
        role="management", campus_id=body.campus_id,
    )
    return ProvisionedUserOut(**created)


@router.get("/campuses", response_model=list[CampusOut])
async def list_campuses(
    _session: Annotated[CurrentSession, Depends(session_with_roles("super_admin"))],
    sb: PostgresClient = Depends(get_data_client),
):
    return await sb.select_service("campuses", {"select": "id,name,code", "order": "name.asc"})


@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(
    session: Annotated[CurrentSession, Depends(session_with_roles("authority"))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Departments on the authority's own campus only."""
    if session.user.campus_id is None:
        return []
    return await sb.select_service(
        "departments",
        {"select": "id,name", "campus_id": f"eq.{session.user.campus_id}", "order": "name.asc"},
    )


@router.get("/registrations", response_model=list[RegistrationOut])
async def pending_registrations(
    _session: Annotated[CurrentSession, Depends(session_with_roles("authority"))],
    sb: PostgresClient = Depends(get_data_client),
):
    return await list_pending_registrations(sb)


@router.post("/registrations/{request_id}/approve", response_model=ProvisionedUserOut, status_code=201)
async def approve(
    request_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles("authority"))],
    sb: PostgresClient = Depends(get_data_client),
    accounts: AccountDirectory = Depends(get_account_directory),
):
    """Approves a pending student request. The student joins the approver's campus. Sends a real email."""
    created = await approve_registration(
        sb=sb, accounts=accounts, actor=session.user, request_id=request_id,
    )
    return ProvisionedUserOut(**created)


@router.post("/registrations/{request_id}/reject", response_model=RegistrationOut)
async def reject(
    request_id: UUID,
    body: RejectRegistrationRequest,
    session: Annotated[CurrentSession, Depends(session_with_roles("authority"))],
    sb: PostgresClient = Depends(get_data_client),
):
    row = await reject_registration(sb=sb, actor=session.user, request_id=request_id, reason=body.reason)
    return RegistrationOut(**row)
