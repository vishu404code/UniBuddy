"""Campus-queue inquiries have no department. Listing or creating them must not fail on the response model.
Found while testing the Student "Raise as a query" flow: TicketOut declared department_id as required, so any
ticket without a department returned HTTP 500. Fixtures only."""

from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.tickets import TicketOut


def _row(**changes):
    now = datetime.now(timezone.utc)
    row = {
        "id": uuid4(), "ticket_number": "UB-0001", "subject": "FIXTURE inquiry", "question": "FIXTURE question",
        "description": None, "priority": "medium", "status": "submitted", "campus_id": uuid4(),
        "department_id": None, "student_id": uuid4(), "assigned_faculty_id": None, "source_message_id": None,
        "created_at": now, "updated_at": now,
    }
    row.update(changes)
    return row


def test_a_campus_queue_ticket_without_a_department_is_a_valid_response():
    ticket = TicketOut(**_row())

    assert ticket.department_id is None


def test_a_departmental_ticket_still_validates_its_department():
    department = uuid4()

    assert TicketOut(**_row(department_id=department)).department_id == department
