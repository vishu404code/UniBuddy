from collections import Counter
from datetime import datetime, timezone
from statistics import mean
from typing import Any

from app.services.supabase_client import SupabaseClient


async def student_dashboard(sb: SupabaseClient, access_token: str) -> dict[str, Any]:
    tickets = await sb.select_as_user(access_token, "tickets", {"select": "status"})
    questions = await sb.select_as_user(access_token, "messages", {"select": "id", "role": "eq.user"})
    by_status = Counter(row["status"] for row in tickets)
    return {
        "total_questions": len(questions),
        "total_tickets": len(tickets),
        "tickets_by_status": {status: by_status.get(status, 0) for status in ["submitted", "assigned", "in_progress", "resolved"]},
        "generated_at": datetime.now(timezone.utc),
    }


def _rate(resolved: int, total: int) -> float | None:
    return round(resolved / total, 4) if total else None


def _response_hours(ticket_created: datetime, first_reply: datetime) -> float:
    return (first_reply - ticket_created).total_seconds() / 3600


def _group(groups: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    return groups.setdefault(key, {"total": 0, "resolved": 0, "response_hours": []})


async def management_stats(sb: SupabaseClient) -> dict[str, Any]:
    """Aggregates only. Returns counts and rates, never ticket contents."""
    tickets = await sb.select_all_service(
        "tickets", {"select": "id,campus_id,department_id,status,created_at", "order": "id.asc"}
    )
    replies = await sb.select_all_service(
        "ticket_events", {"select": "ticket_id,created_at", "event_type": "eq.reply", "order": "id.asc"}
    )
    campuses = {row["id"]: row["name"] for row in await sb.select_all_service("campuses", {"select": "id,name"})}
    departments = {
        row["id"]: row["name"] for row in await sb.select_all_service("departments", {"select": "id,name"})
    }

    first_reply_by_ticket: dict[str, datetime] = {}
    for reply in replies:
        created = datetime.fromisoformat(reply["created_at"])
        current = first_reply_by_ticket.get(reply["ticket_id"])
        if current is None or created < current:
            first_reply_by_ticket[reply["ticket_id"]] = created

    by_campus: dict[str, dict[str, Any]] = {}
    by_department: dict[str, dict[str, Any]] = {}
    overall = {"total": 0, "resolved": 0, "response_hours": []}
    for ticket in tickets:
        resolved = ticket["status"] == "resolved"
        created = datetime.fromisoformat(ticket["created_at"])
        hours = None
        first_reply = first_reply_by_ticket.get(ticket["id"])
        if first_reply is not None:
            hours = _response_hours(created, first_reply)
        for bucket in (
            _group(by_campus, ticket["campus_id"]),
            _group(by_department, ticket["department_id"]),
            overall,
        ):
            bucket["total"] += 1
            bucket["resolved"] += int(resolved)
            if hours is not None:
                bucket["response_hours"].append(hours)

    def to_group(identifier: str, names: dict[str, str], stats: dict[str, Any]) -> dict[str, Any]:
        hours = stats["response_hours"]
        return {
            "id": identifier,
            "name": names.get(identifier, "Unknown"),
            "total_tickets": stats["total"],
            "resolved_tickets": stats["resolved"],
            "resolution_rate": _rate(stats["resolved"], stats["total"]),
            "avg_first_response_hours": round(mean(hours), 2) if hours else None,
        }

    return {
        "total_tickets": overall["total"],
        "resolved_tickets": overall["resolved"],
        "resolution_rate": _rate(overall["resolved"], overall["total"]),
        "avg_first_response_hours": round(mean(overall["response_hours"]), 2) if overall["response_hours"] else None,
        "campuses": [to_group(cid, campuses, stats) for cid, stats in by_campus.items()],
        "departments": [to_group(did, departments, stats) for did, stats in by_department.items()],
        "generated_at": datetime.now(timezone.utc),
    }
