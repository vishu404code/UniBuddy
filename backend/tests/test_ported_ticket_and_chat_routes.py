"""Routes ported from the finalized UI's backend line onto this deployed line:
POST /tickets (Submit Inquiry) and DELETE /chat/conversations/{id} (owner-only). Fixtures only."""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.middleware.auth import get_profile_repository, get_token_verifier
from app.services.providers import get_data_client
from tests.conftest import FakeProfileRepository, make_profile
from tests import fakes
from tests.fakes import FakeDataClient

CAMPUS = str(uuid4())
STUDENT = str(uuid4())
OTHER_STUDENT = str(uuid4())


class _Verifier:
    def verify(self, token):
        return UUID(token)


def _client(sb):
    profiles = {
        STUDENT: make_profile(STUDENT, role="student", campus_id=CAMPUS),
        OTHER_STUDENT: make_profile(OTHER_STUDENT, role="student", campus_id=CAMPUS),
    }
    app.dependency_overrides[get_token_verifier] = lambda: _Verifier()
    app.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(profiles)
    app.dependency_overrides[get_data_client] = lambda: sb
    return TestClient(app)


def test_a_student_inquiry_is_saved_for_the_campus_queue_and_returned(monkeypatch):
    # The real table fills these columns with NULL or now(); the fake needs the same values to answer like Postgres.
    monkeypatch.setitem(fakes.ROW_DEFAULTS, "tickets", {"assigned_faculty_id": None, "source_message_id": None,
                                                        "updated_at": "2026-11-21T00:00:00+00:00"})
    sb = FakeDataClient()
    try:
        response = _client(sb).post(
            f"{settings.api_v1_prefix}/tickets",
            headers={"Authorization": f"Bearer {STUDENT}"},
            json={"subject": "FIXTURE inquiry", "question": "FIXTURE question", "department_id": None, "priority": "medium"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["ticket"]["subject"] == "FIXTURE inquiry"
    assert body["ticket"]["department_id"] is None
    assert len(sb.tables["tickets"]) == 1


def test_an_inquiry_to_another_campus_department_is_refused():
    sb = FakeDataClient()
    sb.tables["departments"].append({"id": str(uuid4()), "campus_id": str(uuid4()), "name": "Elsewhere"})
    department = sb.tables["departments"][0]["id"]
    try:
        response = _client(sb).post(
            f"{settings.api_v1_prefix}/tickets",
            headers={"Authorization": f"Bearer {STUDENT}"},
            json={"subject": "FIXTURE inquiry", "question": "FIXTURE question", "department_id": department},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code in (400, 422)
    assert sb.tables["tickets"] == []


def test_a_student_deletes_only_their_own_conversation():
    sb = FakeDataClient()
    conversation = str(uuid4())
    sb.tables["conversations"].append({"id": conversation, "user_id": STUDENT, "title": "FIXTURE"})
    try:
        client = _client(sb)
        refused = client.delete(f"{settings.api_v1_prefix}/chat/conversations/{conversation}",
                                headers={"Authorization": f"Bearer {OTHER_STUDENT}"})
        deleted = client.delete(f"{settings.api_v1_prefix}/chat/conversations/{conversation}",
                                headers={"Authorization": f"Bearer {STUDENT}"})
    finally:
        app.dependency_overrides.clear()

    assert refused.status_code == 404
    assert deleted.status_code == 204
    assert sb.tables["conversations"] == []
