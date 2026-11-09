from datetime import datetime, timezone
from uuid import UUID

from app.schemas.auth import CurrentUser
from app.services.auth_admin import AuthAdminClient
from app.services.documents import DocumentConflict, DocumentNotFound
from app.services.provisioning import provision_user
from app.services.supabase_client import SupabaseClient


async def list_pending_registrations(sb: SupabaseClient) -> list[dict]:
    return await sb.select_service(
        "registration_requests",
        {"select": "id,email,full_name,requested_at", "status": "eq.pending", "order": "requested_at.asc",
         "limit": "100"},
    )


async def _pending_request(sb: SupabaseClient, request_id: UUID) -> dict:
    rows = await sb.select_service("registration_requests", {"select": "*", "id": f"eq.{request_id}"})
    if not rows:
        raise DocumentNotFound("Registration request not found")
    if rows[0]["status"] != "pending":
        raise DocumentConflict("This request has already been decided")
    return rows[0]


async def approve_registration(
    *,
    sb: SupabaseClient,
    auth_admin: AuthAdminClient,
    actor: CurrentUser,
    request_id: UUID,
) -> dict:
    """Approves a pending student request. The student joins the approving authority's campus.

    The account is created through the same audited provisioning flow as any invitation. The
    request is marked approved only after the invitation succeeds, so a failure leaves it pending.
    """
    request = await _pending_request(sb, request_id)
    created = await provision_user(
        sb=sb, auth_admin=auth_admin, actor=actor, email=request["email"], full_name=request["full_name"],
        role="student", department_id=None,
    )
    await sb.update_service(
        "registration_requests",
        {"id": f"eq.{request_id}", "status": "eq.pending"},
        {"status": "approved", "decided_by": str(actor.id),
         "decided_at": datetime.now(timezone.utc).isoformat()},
    )
    return created


async def reject_registration(
    *, sb: SupabaseClient, actor: CurrentUser, request_id: UUID, reason: str | None
) -> dict:
    await _pending_request(sb, request_id)
    updated = await sb.update_service(
        "registration_requests",
        {"id": f"eq.{request_id}", "status": "eq.pending"},
        {"status": "rejected", "decided_by": str(actor.id),
         "decided_at": datetime.now(timezone.utc).isoformat(), "decision_reason": reason},
    )
    if not updated:
        raise DocumentConflict("This request has already been decided")
    return updated[0]
