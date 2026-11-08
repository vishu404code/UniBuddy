from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.tickets import TicketDetailOut, TicketOut, TicketUpdateRequest
from app.services.providers import get_supabase_client
from app.services.supabase_client import SupabaseClient
from app.services.tickets import get_ticket_detail, update_ticket

router = APIRouter(prefix="/tickets", tags=["tickets"])
ANY_SIGNED_IN = ("student", "faculty", "authority", "management")
STAFF_ROLES = ("faculty", "authority")


@router.get("", response_model=list[TicketOut])
async def list_tickets(
    session: Annotated[CurrentSession, Depends(session_with_roles(*ANY_SIGNED_IN))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    return await sb.select_as_user(session.access_token, "tickets", {"select": "*", "order": "created_at.desc"})


@router.get("/{ticket_id}", response_model=TicketDetailOut)
async def get_ticket(
    ticket_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*ANY_SIGNED_IN))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    return await get_ticket_detail(sb, session.access_token, ticket_id)


@router.patch("/{ticket_id}", response_model=TicketDetailOut)
async def patch_ticket(
    ticket_id: UUID,
    body: TicketUpdateRequest,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STAFF_ROLES))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    return await update_ticket(
        sb=sb,
        user=session.user,
        access_token=session.access_token,
        ticket_id=ticket_id,
        body=body,
    )
