"""Replies and status changes on a forwarded ticket, as each staff role may make them.
Visibility of tickets is enforced by row-level security (see the tickets_select policy); these tests
cover the service rules that decide who may write. No network calls."""

from uuid import UUID, uuid4

import pytest

from app.schemas.tickets import TicketUpdateRequest
from app.services.documents import DocumentForbidden
from app.services.tickets import get_ticket_detail, update_ticket
from tests.conftest import make_profile
from tests.fakes import FakeDataClient


def _ticket(sb, campus_id, department_id, assigned=None):
    ticket_id = str(uuid4())
    student_id = str(uuid4())
    sb.tables["tickets"].append({
        "id": ticket_id, "ticket_number": "UB-0101", "student_id": student_id, "campus_id": campus_id,
        "department_id": department_id, "assigned_faculty_id": assigned, "subject": "LOA", "question": "Q?",
        "description": None, "priority": "medium", "status": "submitted", "source_message_id": None,
        "created_at": "2026-11-17T00:00:00+00:00", "updated_at": "2026-11-17T00:00:00+00:00",
    })
    return ticket_id, student_id


@pytest.mark.asyncio
async def test_authority_can_reply_and_resolve_a_departmental_ticket_without_taking_it():
    sb = FakeDataClient()
    campus = str(uuid4())
    authority = make_profile(str(uuid4()), role="authority", campus_id=campus)
    ticket_id, student_id = _ticket(sb, campus, str(uuid4()))

    await update_ticket(sb=sb, user=authority, access_token=str(authority.id), ticket_id=UUID(ticket_id),
                        body=TicketUpdateRequest(reply="Please bring the form to the office."))
    await update_ticket(sb=sb, user=authority, access_token=str(authority.id), ticket_id=UUID(ticket_id),
                        body=TicketUpdateRequest(status="resolved"))

    detail = await get_ticket_detail(sb, str(authority.id), UUID(ticket_id))
    assert detail["ticket"]["status"] == "resolved"
    assert [e["event_type"] for e in detail["events"]] == ["reply", "status_change"]
    notes = [n for n in sb.tables["notifications"] if n["user_id"] == student_id]
    assert len(notes) == 2


@pytest.mark.asyncio
async def test_faculty_must_take_a_ticket_before_replying_and_only_the_assignee_may_reply():
    sb = FakeDataClient()
    campus = str(uuid4())
    dept = str(uuid4())
    taker = make_profile(str(uuid4()), role="faculty", campus_id=campus, department_id=dept)
    other = make_profile(str(uuid4()), role="faculty", campus_id=campus, department_id=dept)
    ticket_id, _ = _ticket(sb, campus, dept)

    with pytest.raises(DocumentForbidden):
        await update_ticket(sb=sb, user=taker, access_token=str(taker.id), ticket_id=UUID(ticket_id),
                            body=TicketUpdateRequest(reply="Too early."))

    await update_ticket(sb=sb, user=taker, access_token=str(taker.id), ticket_id=UUID(ticket_id),
                        body=TicketUpdateRequest(take_ticket=True))
    await update_ticket(sb=sb, user=taker, access_token=str(taker.id), ticket_id=UUID(ticket_id),
                        body=TicketUpdateRequest(reply="I will look into it."))
    assert sb.tables["tickets"][0]["assigned_faculty_id"] == str(taker.id)

    with pytest.raises(DocumentForbidden):
        await update_ticket(sb=sb, user=other, access_token=str(other.id), ticket_id=UUID(ticket_id),
                            body=TicketUpdateRequest(reply="Not my ticket."))


@pytest.mark.asyncio
async def test_only_faculty_can_take_a_ticket_and_authority_cannot():
    sb = FakeDataClient()
    campus = str(uuid4())
    authority = make_profile(str(uuid4()), role="authority", campus_id=campus)
    ticket_id, _ = _ticket(sb, campus, str(uuid4()))

    with pytest.raises(DocumentForbidden):
        await update_ticket(sb=sb, user=authority, access_token=str(authority.id), ticket_id=UUID(ticket_id),
                            body=TicketUpdateRequest(take_ticket=True))
