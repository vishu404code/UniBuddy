"""Ticket correctness: a campus-less submitter gets a clear error, and no ticket with an invented campus is written.

Synthetic fixtures and the in-memory fake only.
"""

from uuid import uuid4

import pytest

from app.schemas.auth import CurrentUser
from app.services.documents import DocumentError
from app.services.tickets import create_ticket
from tests.fakes import FakeDataClient


@pytest.mark.asyncio
async def test_a_student_without_a_campus_gets_a_clear_error_and_no_ticket_is_written():
    sb = FakeDataClient()
    student = CurrentUser(id=uuid4(), email="s@example.com", full_name="S", role="student",
                          campus_id=None, department_id=None)

    with pytest.raises(DocumentError) as caught:
        await create_ticket(sb=sb, user=student, access_token="student-token",
                            subject="Fee question", question="When is the fee due?")

    assert caught.value.status_code == 400
    assert "no campus assigned" in caught.value.message
    assert sb.tables["tickets"] == []
    assert sb.tables["ticket_events"] == []
