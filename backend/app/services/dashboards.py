from datetime import datetime, timezone
from typing import Any

from app.services.supabase_client import SupabaseClient

TICKET_STATUSES = ["submitted", "assigned", "in_progress", "resolved"]


async def student_dashboard(sb: SupabaseClient, access_token: str) -> dict[str, Any]:
    total_tickets = await sb.count_as_user(access_token, "tickets", {})
    by_status = {}
    for status in TICKET_STATUSES:
        by_status[status] = await sb.count_as_user(access_token, "tickets", {"status": f"eq.{status}"})
    total_questions = await sb.count_as_user(access_token, "messages", {"role": "eq.user"})
    return {
        "total_questions": total_questions,
        "total_tickets": total_tickets,
        "tickets_by_status": by_status,
        "generated_at": datetime.now(timezone.utc),
    }


async def staff_dashboard(sb: SupabaseClient, access_token: str) -> dict[str, Any]:
    stats = await sb.rpc_as_user(access_token, "staff_dashboard_stats", {})
    return {**stats, "generated_at": datetime.now(timezone.utc)}


async def management_stats(sb: SupabaseClient) -> dict[str, Any]:
    """Aggregates computed in the database. Contains no ticket or student contents."""
    return await sb.rpc_service("management_ticket_stats", {})
