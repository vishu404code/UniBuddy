from typing import Any
from uuid import UUID, uuid4

from app.schemas.auth import CurrentUser
from app.schemas.tickets import TicketUpdateRequest
from app.services.documents import DocumentConflict, DocumentError, DocumentForbidden, DocumentNotFound
from app.services.postgres_client import PostgresClient

STATUS_ORDER = {"submitted": 0, "assigned": 1, "in_progress": 2, "resolved": 3}
STATUS_LABELS = {
    "submitted": "Submitted",
    "assigned": "Assigned",
    "in_progress": "In Progress",
    "resolved": "Resolved",
}


async def get_ticket_detail(sb: PostgresClient, access_token: str, ticket_id: UUID) -> dict[str, Any]:
    rows = await sb.select_as_user(access_token, "tickets", {"select": "*", "id": f"eq.{ticket_id}"})
    if not rows:
        raise DocumentNotFound("Ticket not found")
    events = await sb.select_as_user(
        access_token,
        "ticket_events",
        {"select": "id,event_type,note,actor_id,created_at", "ticket_id": f"eq.{ticket_id}", "order": "created_at.asc"},
    )
    return {"ticket": rows[0], "events": events}


async def create_ticket(
    *,
    sb: PostgresClient,
    user: CurrentUser,
    access_token: str,
    subject: str,
    question: str,
    department_id: UUID | None = None,
    priority: str = "medium",
    description: str | None = None,
) -> dict[str, Any]:
    ticket_id = uuid4()
    if department_id is not None and user.campus_id is not None:
        department = await sb.select_service(
            "departments",
            {"select": "id", "id": f"eq.{department_id}", "campus_id": f"eq.{user.campus_id}"},
        )
        if not department:
            raise DocumentError("Department does not belong to your campus")

    campus_id = user.campus_id or uuid4()
    row = {
        "id": str(ticket_id),
        "student_id": str(user.id),
        "campus_id": str(campus_id),
        "department_id": str(department_id) if department_id is not None else None,
        "subject": subject[:120].strip(),
        "question": question.strip(),
        "description": description.strip() if description else None,
        "priority": priority,
        "status": "submitted",
    }
    await sb.insert_service("tickets", [row])

    tickets = await sb.select_service("tickets", {"select": "*", "id": f"eq.{ticket_id}"})
    ticket = tickets[0] if tickets else row
    ticket_num = ticket.get("ticket_number") or str(ticket_id)[:8]

    try:
        await sb.insert_service(
            "ticket_events",
            [
                {
                    "id": str(uuid4()),
                    "ticket_id": str(ticket_id),
                    "actor_id": str(user.id),
                    "event_type": "submission",
                    "note": "Query submitted by student",
                }
            ],
        )
    except Exception:
        pass

    try:
        notifs = [
            {
                "id": str(uuid4()),
                "user_id": str(user.id),
                "text": f"Your ticket {ticket_num} was created.",
                "ticket_id": str(ticket_id),
            }
        ]
        faculty_filters = {"role": "eq.faculty"}
        if department_id is not None:
            faculty_filters["department_id"] = f"eq.{department_id}"
        elif user.campus_id is not None:
            faculty_filters["campus_id"] = f"eq.{user.campus_id}"

        faculty_rows = await sb.select_service("profiles", {"select": "id", **faculty_filters})
        for fac in faculty_rows:
            notifs.append(
                {
                    "id": str(uuid4()),
                    "user_id": str(fac["id"]),
                    "text": f"New student query {ticket_num}: {subject[:60]}",
                    "ticket_id": str(ticket_id),
                }
            )
        await sb.insert_service("notifications", notifs)
    except Exception:
        pass

    return {"ticket": ticket, "events": []}


def _check_transition(current: str, requested: str) -> None:
    if current == "resolved":
        raise DocumentConflict("Resolved tickets cannot be changed")
    if STATUS_ORDER[requested] <= STATUS_ORDER[current]:
        raise DocumentError(f"Ticket cannot move from {STATUS_LABELS[current]} to {STATUS_LABELS[requested]}")


async def update_ticket(
    *,
    sb: PostgresClient,
    user: CurrentUser,
    access_token: str,
    ticket_id: UUID,
    body: TicketUpdateRequest,
) -> dict[str, Any]:
    rows = await sb.select_as_user(access_token, "tickets", {"select": "*", "id": f"eq.{ticket_id}"})
    if not rows:
        raise DocumentNotFound("Ticket not found")
    ticket = rows[0]
    current_status = ticket["status"]
    me = str(user.id)
    assigned_to = str(ticket["assigned_faculty_id"]) if ticket["assigned_faculty_id"] else None

    if body.take_ticket:
        if user.role != "faculty":
            raise DocumentForbidden("Only faculty can take a ticket")
        if assigned_to not in (None, me):
            raise DocumentConflict("Ticket is already assigned to another faculty member")

    is_assignee = assigned_to == me or (body.take_ticket and assigned_to is None)
    if body.status is not None or body.reply is not None:
        if user.role == "faculty" and not is_assignee:
            raise DocumentForbidden("Take this ticket before changing its status or replying")

    updates: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    notify_text: str | None = None

    if body.take_ticket:
        updates["assigned_faculty_id"] = me
        if current_status == "submitted":
            updates["status"] = "assigned"
            current_status = "assigned"
        events.append({"event_type": "assignment", "note": "Ticket taken by faculty"})

    if body.status is not None:
        _check_transition(current_status, body.status)
        updates["status"] = body.status
        events.append(
            {"event_type": "status_change", "note": f"Status changed to {STATUS_LABELS[body.status]}"}
        )
        notify_text = f"Ticket {ticket['ticket_number']} is now {STATUS_LABELS[body.status]}."

    if body.reply is not None:
        if current_status == "resolved":
            raise DocumentConflict("Resolved tickets cannot receive replies")
        events.append({"event_type": "reply", "note": body.reply.strip()})
        notify_text = notify_text or f"Faculty replied to ticket {ticket['ticket_number']}."

    if not updates and not events:
        return await get_ticket_detail(sb, access_token, ticket_id)

    if updates:
        filters = {"id": f"eq.{ticket_id}", "status": f"eq.{ticket['status']}"}
        updated = await sb.update_service("tickets", filters, updates)
        if not updated:
            raise DocumentConflict("Ticket was changed by someone else; reload and try again")

    actor = me
    await sb.insert_service(
        "ticket_events",
        [
            {
                "id": str(uuid4()),
                "ticket_id": str(ticket_id),
                "actor_id": actor,
                "event_type": event["event_type"],
                "note": event["note"],
            }
            for event in events
        ],
    )
    if notify_text:
        await sb.insert_service(
            "notifications",
            [
                {
                    "id": str(uuid4()),
                    "user_id": str(ticket["student_id"]),
                    "text": notify_text,
                    "ticket_id": str(ticket_id),
                }
            ],
        )
    return await get_ticket_detail(sb, access_token, ticket_id)
