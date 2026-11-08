from typing import Any
from uuid import UUID

from app.services.documents import DocumentNotFound
from app.services.supabase_client import SupabaseClient


async def mark_notification_read(
    *, sb: SupabaseClient, access_token: str, notification_id: UUID
) -> dict[str, Any]:
    rows = await sb.select_as_user(
        access_token, "notifications", {"select": "*", "id": f"eq.{notification_id}"}
    )
    if not rows:
        raise DocumentNotFound("Notification not found")
    if rows[0]["is_read"]:
        return rows[0]
    updated = await sb.update_service("notifications", {"id": f"eq.{notification_id}"}, {"is_read": True})
    return updated[0] if updated else rows[0]
