"""Tickets with and without a department. A question sent without a department (the campus queue) must
list and open like any other ticket. Authorization is unchanged: the fake client only returns what it is given."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.middleware.auth import get_profile_repository, get_token_verifier
from app.schemas.tickets import TicketDetailOut, TicketOut
from app.services.providers import get_data_client
from tests.conftest import FakeProfileRepository, make_profile
from tests.fakes import FakeDataClient

API = settings.api_v1_prefix
CAMPUS = str(uuid4())
DEPARTMENT = str(uuid4())
STUDENT_ID = str(uuid4())
AUTHORITY_ID = str(uuid4())
FACULTY_ID = str(uuid4())
NOW = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc).isoformat()


class _Verifier:
    def verify(self, token):
        import uuid

        return uuid.UUID(token)


def _auth(user_id):
    return {"Authorization": f"Bearer {user_id}"}


def _ticket(number, department_id):
    return {
        "id": str(uuid4()), "ticket_number": number, "subject": f"Subject {number}", "question": "Q?",
        "description": None, "priority": "medium", "status": "submitted", "campus_id": CAMPUS,
        "department_id": department_id, "student_id": STUDENT_ID, "assigned_faculty_id": None,
        "source_message_id": str(uuid4()), "created_at": NOW, "updated_at": NOW,
    }


@pytest.fixture
def client():
    profiles = {
        STUDENT_ID: make_profile(STUDENT_ID, role="student", campus_id=CAMPUS),
        AUTHORITY_ID: make_profile(AUTHORITY_ID, role="authority", campus_id=CAMPUS),
        FACULTY_ID: make_profile(FACULTY_ID, role="faculty", campus_id=CAMPUS, department_id=DEPARTMENT),
    }
    sb = FakeDataClient()
    sb.tables["tickets"] = [_ticket("UB-0001", DEPARTMENT), _ticket("UB-0002", None)]
    app.dependency_overrides[get_token_verifier] = lambda: _Verifier()
    app.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(profiles)
    app.dependency_overrides[get_data_client] = lambda: sb
    try:
        yield TestClient(app), sb
    finally:
        app.dependency_overrides.clear()


def test_ticket_schema_accepts_a_missing_department_and_still_requires_a_uuid_when_present():
    base = _ticket("UB-9", None)
    assert TicketOut(**base).department_id is None
    assert str(TicketOut(**_ticket("UB-9", DEPARTMENT)).department_id) == DEPARTMENT
    with pytest.raises(Exception):
        TicketOut(**{**base, "department_id": "not-a-uuid"})


def test_detail_schema_accepts_a_ticket_without_a_department():
    detail = TicketDetailOut(ticket=_ticket("UB-9", None), events=[])
    assert detail.ticket.department_id is None


def test_student_list_returns_tickets_with_and_without_a_department(client):
    test_client, _ = client
    response = test_client.get(f"{API}/tickets?limit=50", headers=_auth(STUDENT_ID))
    assert response.status_code == 200
    items = response.json()["items"]
    assert sorted(item["ticket_number"] for item in items) == ["UB-0001", "UB-0002"]
    by_number = {item["ticket_number"]: item for item in items}
    assert by_number["UB-0001"]["department_id"] == DEPARTMENT
    assert by_number["UB-0002"]["department_id"] is None


def test_authority_list_returns_campus_queue_tickets(client):
    test_client, _ = client
    response = test_client.get(f"{API}/tickets?limit=50", headers=_auth(AUTHORITY_ID))
    assert response.status_code == 200
    assert {item["ticket_number"] for item in response.json()["items"]} == {"UB-0001", "UB-0002"}


def test_detail_opens_a_ticket_without_a_department(client):
    test_client, sb = client
    no_dept = next(t for t in sb.tables["tickets"] if t["ticket_number"] == "UB-0002")
    response = test_client.get(f"{API}/tickets/{no_dept['id']}", headers=_auth(STUDENT_ID))
    assert response.status_code == 200
    body = response.json()
    assert body["ticket"]["ticket_number"] == "UB-0002"
    assert body["ticket"]["department_id"] is None


def test_detail_opens_a_ticket_with_a_department(client):
    test_client, sb = client
    with_dept = next(t for t in sb.tables["tickets"] if t["ticket_number"] == "UB-0001")
    response = test_client.get(f"{API}/tickets/{with_dept['id']}", headers=_auth(FACULTY_ID))
    assert response.status_code == 200
    assert response.json()["ticket"]["department_id"] == DEPARTMENT


def test_unknown_ticket_is_still_not_found(client):
    test_client, _ = client
    response = test_client.get(f"{API}/tickets/{uuid4()}", headers=_auth(STUDENT_ID))
    assert response.status_code == 404
