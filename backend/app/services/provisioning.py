from uuid import UUID

from app.schemas.auth import CurrentUser
from app.services.auth_admin import AuthAdminClient, AuthAdminError
from app.services.documents import DocumentConflict, DocumentError, DocumentForbidden
from app.services.supabase_client import SupabaseClient, SupabaseError

REJECTION_STATUS = {
    "not_authority": (403, "Only authority users can onboard students and faculty"),
    "no_campus": (403, "Your account has no campus assigned"),
    "invalid_role": (422, "This role cannot be provisioned here"),
    "department_required": (422, "Faculty need a department"),
    "department_not_in_campus": (422, "The department does not belong to your campus"),
    "email_exists": (409, "An account with this email already exists in UniBuddy"),
}


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
    """Invites one student or faculty member into the actor's campus.

    Order matters. The email domain must be on the server-side allowlist, and it fails closed
    when the allowlist is empty. The database precheck runs next, so an invalid request never
    causes an invitation. If the profile cannot be completed after the invite, the new auth user is
    deleted again, and the audit trail records the compensation.
    """
    if not allowed_domains:
        raise ProvisioningError(503, "User provisioning is not configured")

    email = email.strip().lower()
    if email_domain(email) not in allowed_domains:
        await _record(sb, actor, email, role, department_id, "failed", "email_domain_not_allowed")
        raise ProvisioningError(422, "Invitations can only be sent to approved university email domains")

    precheck = await sb.rpc_service(
        "provisioning_precheck",
        {
            "p_actor": str(actor.id),
            "p_email": email,
            "p_role": role,
            "p_department": str(department_id) if department_id else None,
        },
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
            "provisioning_complete",
            {
                "p_actor": str(actor.id),
                "p_user_id": str(user_id),
                "p_email": email,
                "p_full_name": full_name,
                "p_role": role,
                "p_department": str(department_id) if department_id else None,
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
