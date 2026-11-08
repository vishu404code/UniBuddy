from uuid import UUID

from app.schemas.auth import CurrentUser
from app.services.auth_admin import AuthAdminClient, AuthAdminError
from app.services.documents import DocumentError
from app.services.supabase_client import SupabaseClient, SupabaseError

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


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1]


class ProvisioningError(DocumentError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


async def _record(sb: SupabaseClient, actor: CurrentUser, email: str, role: str, department_id: UUID | None,
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
    sb: SupabaseClient,
    auth_admin: AuthAdminClient,
    actor: CurrentUser,
    email: str,
    full_name: str,
    role: str,
    department_id: UUID | None,
    allowed_domains: frozenset[str],
    rpcs: tuple[str, str],
    scope_args: dict,
) -> dict:
    """Shared flow: domain allowlist, database precheck, Supabase invite, database completion.

    The invite happens only after every check has passed. If completion fails after the invite,
    the new login is deleted again and the compensation is audited.
    """
    if not allowed_domains:
        raise ProvisioningError(503, "User provisioning is not configured")

    email = email.strip().lower()
    if email_domain(email) not in allowed_domains:
        await _record(sb, actor, email, role, department_id, "failed", "email_domain_not_allowed")
        raise ProvisioningError(422, "Invitations can only be sent to approved university email domains")

    precheck_rpc, complete_rpc = rpcs
    precheck = await sb.rpc_service(
        precheck_rpc,
        {"p_actor": str(actor.id), "p_email": email, "p_role": role, **scope_args["precheck"]},
    )
    if not precheck["ok"]:
        status_code, message = REJECTION_STATUS.get(precheck["reason"], (422, "Request rejected"))
        raise ProvisioningError(status_code, message)

    try:
        user_id = await auth_admin.invite_user(email, full_name)
    except AuthAdminError as exc:
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
    except SupabaseError as exc:
        try:
            await auth_admin.delete_user(user_id)
            await _record(sb, actor, email, role, department_id, "compensated", "profile_failed", user_id)
        except AuthAdminError:
            await _record(sb, actor, email, role, department_id, "failed", "cleanup_failed", user_id)
        raise ProvisioningError(502, "The account could not be completed. Nothing was left behind.") from exc

    return {**created, "status": "invited"}


async def provision_user(
    *,
    sb: SupabaseClient,
    auth_admin: AuthAdminClient,
    actor: CurrentUser,
    email: str,
    full_name: str,
    role: str,
    department_id: UUID | None,
    allowed_domains: frozenset[str],
) -> dict:
    """A campus authority invites a student or faculty member into its own campus.

    The campus always comes from the actor's profile. The client never supplies it.
    """
    department = str(department_id) if department_id else None
    return await _run_provisioning(
        sb=sb, auth_admin=auth_admin, actor=actor, email=email, full_name=full_name, role=role,
        department_id=department_id, allowed_domains=allowed_domains, rpcs=AUTHORITY_RPCS,
        scope_args={"precheck": {"p_department": department}, "complete": {"p_department": department}},
    )


async def provision_by_super_admin(
    *,
    sb: SupabaseClient,
    auth_admin: AuthAdminClient,
    actor: CurrentUser,
    email: str,
    full_name: str,
    role: str,
    campus_id: UUID | None,
    allowed_domains: frozenset[str],
) -> dict:
    """Super Admin invites an authority (campus required) or management account (campus optional).

    The campus is an administrative choice made by Super Admin, validated in the database. It is
    never chosen by the invitee.
    """
    campus = str(campus_id) if campus_id else None
    return await _run_provisioning(
        sb=sb, auth_admin=auth_admin, actor=actor, email=email, full_name=full_name, role=role,
        department_id=None, allowed_domains=allowed_domains, rpcs=SUPER_ADMIN_RPCS,
        scope_args={"precheck": {"p_campus": campus}, "complete": {"p_campus": campus}},
    )
