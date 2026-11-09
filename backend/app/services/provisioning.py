from uuid import UUID

from app.schemas.auth import CurrentUser
from app.services.account_directory import AccountDirectory, AccountDirectoryError
from app.services.documents import DocumentError
from app.services.postgres_client import PostgresClient
from app.services.errors import DataServiceError

REJECTION_STATUS = {
    "not_authority": (403, "Only authority users can onboard students and faculty"),
    "not_super_admin": (403, "Only Super Admin can provision authority and management accounts"),
    "no_campus": (403, "Your account has no campus assigned"),
    "invalid_role": (422, "This role cannot be provisioned here"),
    "department_required": (422, "Faculty need a department"),
    "department_not_in_campus": (422, "The department does not belong to your campus"),
    "campus_required": (422, "Choose a campus for this authority account"),
    "campus_not_found": (422, "The campus does not exist"),
    "email_exists": (409, "An account with this email already exists in UniBuddy"),
}

AUTHORITY_RPCS = ("provisioning_precheck", "provisioning_complete")
SUPER_ADMIN_RPCS = ("super_admin_provision_precheck", "super_admin_provision_complete")


class ProvisioningError(DocumentError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


async def _record(sb: PostgresClient, actor: CurrentUser, email: str, role: str, department_id: UUID | None,
                  outcome: str, reason: str, user_id: UUID | None = None) -> None:
    await sb.rpc_service(
        "provisioning_record_failure",
        {
            "p_actor": str(actor.id),
            "p_email": email,
            "p_role": role,
            "p_department": str(department_id) if department_id else None,
            "p_outcome": outcome,
            "p_reason": reason,
            "p_user_id": str(user_id) if user_id else None,
        },
    )


async def _run_provisioning(
    *,
    sb: PostgresClient,
    accounts: AccountDirectory,
    actor: CurrentUser,
    email: str,
    full_name: str,
    role: str,
    department_id: UUID | None,
    rpcs: tuple[str, str],
    scope_args: dict,
) -> dict:
    """Shared flow: database precheck, account invitation, database completion.

    The invite happens only after every check has passed. If completion fails after the invite,
    the new login is deleted again and the compensation is audited.
    """
    email = email.strip().lower()

    precheck_rpc, complete_rpc = rpcs
    precheck = await sb.rpc_service(
        precheck_rpc,
        {"p_actor": str(actor.id), "p_email": email, "p_role": role, **scope_args["precheck"]},
    )
    if not precheck["ok"]:
        status_code, message = REJECTION_STATUS.get(precheck["reason"], (422, "Request rejected"))
        raise ProvisioningError(status_code, message)

    try:
        user_id = await accounts.invite_user(email, full_name)
    except AccountDirectoryError as exc:
        if exc.code == "account_exists":
            await _record(sb, actor, email, role, department_id, "failed", "account_exists_in_auth")
            raise ProvisioningError(409, "This email already has a login. Ask the user to sign in instead.") from exc
        await _record(sb, actor, email, role, department_id, "failed", exc.code)
        raise ProvisioningError(502, "The invitation could not be sent. Try again later.") from exc

    try:
        created = await sb.rpc_service(
            complete_rpc,
            {
                "p_actor": str(actor.id),
                "p_user_id": str(user_id),
                "p_email": email,
                "p_full_name": full_name,
                "p_role": role,
                **scope_args["complete"],
            },
        )
    except DataServiceError as exc:
        try:
            await accounts.delete_user(user_id)
            await _record(sb, actor, email, role, department_id, "compensated", "profile_failed", user_id)
        except AccountDirectoryError:
            await _record(sb, actor, email, role, department_id, "failed", "cleanup_failed", user_id)
        raise ProvisioningError(502, "The account could not be completed. Nothing was left behind.") from exc

    return {**created, "status": "invited"}


async def provision_user(
    *,
    sb: PostgresClient,
    accounts: AccountDirectory,
    actor: CurrentUser,
    email: str,
    full_name: str,
    role: str,
    department_id: UUID | None,
) -> dict:
    """A campus authority invites a student or faculty member into its own campus.

    The campus always comes from the actor's profile. The client never supplies it.
    """
    department = str(department_id) if department_id else None
    return await _run_provisioning(
        sb=sb, accounts=accounts, actor=actor, email=email, full_name=full_name, role=role,
        department_id=department_id, rpcs=AUTHORITY_RPCS,
        scope_args={"precheck": {"p_department": department}, "complete": {"p_department": department}},
    )


async def provision_by_super_admin(
    *,
    sb: PostgresClient,
    accounts: AccountDirectory,
    actor: CurrentUser,
    email: str,
    full_name: str,
    role: str,
    campus_id: UUID | None,
) -> dict:
    """Super Admin invites an authority (campus required) or management account (campus optional).

    The campus is an administrative choice made by Super Admin, validated in the database. It is
    never chosen by the invitee.
    """
    campus = str(campus_id) if campus_id else None
    return await _run_provisioning(
        sb=sb, accounts=accounts, actor=actor, email=email, full_name=full_name, role=role,
        department_id=None, rpcs=SUPER_ADMIN_RPCS,
        scope_args={"precheck": {"p_campus": campus}, "complete": {"p_campus": campus}},
    )
