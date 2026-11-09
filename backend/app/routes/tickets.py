from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.common import Page
from app.schemas.tickets import TicketDetailOut, TicketOut, TicketUpdateRequest
from app.services.providers import get_data_client
from app.services.postgres_client import PostgresClient
from app.services.tickets import get_ticket_detail, update_ticket

router = APIRouter(prefix="/tickets", tags=["tickets"])
ANY_SIGNED_IN = ("student", "faculty", "authority", "management")
STAFF_ROLES = ("faculty", "authority")


@router.get("", response_model=Page[TicketOut])
async def list_tickets(
    session: Annotated[CurrentSession, Depends(session_with_roles(*ANY_SIGNED_IN))],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Literal["submitted", "assigned", "in_progress", "resolved"] | None = None,
    priority: Literal["low", "medium", "high"] | None = None,
    department_id: UUID | None = None,
    campus_id: UUID | None = None,
    assigned: Literal["me", "unassigned"] | None = None,
    sb: PostgresClient = Depends(get_data_client),
):
    """Tickets the caller may see. Filters narrow the results; they never widen access."""
    filters = {"order": "created_at.desc"}
    if status:
        filters["status"] = f"eq.{status}"
    if priority:
        filters["priority"] = f"eq.{priority}"
    if department_id:
        filters["department_id"] = f"eq.{department_id}"
    if campus_id:
        filters["campus_id"] = f"eq.{campus_id}"
    if assigned == "me":
        filters["assigned_faculty_id"] = f"eq.{session.user.id}"
    elif assigned == "unassigned":
        filters["assigned_faculty_id"] = "is.null"
    rows, total = await sb.select_page_as_user(session.access_token, "tickets", {"select": "*", **filters}, limit, offset)
    return Page[TicketOut](items=rows, total=total, limit=limit, offset=offset)


@router.get("/{ticket_id}", response_model=TicketDetailOut)
async def get_ticket(
    ticket_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*ANY_SIGNED_IN))],
    sb: PostgresClient = Depends(get_data_client),
):
    return await get_ticket_detail(sb, session.access_token, ticket_id)


@router.patch("/{ticket_id}", response_model=TicketDetailOut)
async def patch_ticket(
    ticket_id: UUID,
    body: TicketUpdateRequest,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    sb: PostgresClient = Depends(get_data_client),
):
    return await update_ticket(
        sb=sb,
        user=session.user,
        access_token=session.access_token,
        ticket_id=ticket_id,
        body=body,
    )
