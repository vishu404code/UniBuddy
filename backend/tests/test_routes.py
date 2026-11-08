from uuid import uuid4

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.ai.rag import ABSTAIN_MESSAGE
from app.config import settings
from app.main import app
from app.middleware.auth import get_token_verifier, get_profile_repository
from app.services.providers import get_openai_client, get_supabase_client
from app.services.supabase_client import SupabaseError
from tests.conftest import FakeProfileRepository, make_profile
from tests.fakes import FakeAI, FakeSupabase

API = settings.api_v1_prefix
CAMPUS = str(uuid4())
STUDENT_ID = str(uuid4())
FACULTY_ID = str(uuid4())
MANAGER_ID = str(uuid4())


class _Verifier:
    """Maps the test token string to a user id, standing in for JWT verification."""

    def verify(self, token):
        import uuid

        return uuid.UUID(token)


def _pdf_bytes():
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Fee policy: pay in week two.")
    data = document.tobytes()
    document.close()
    return data


@pytest.fixture
def harness():
    profiles = {
        STUDENT_ID: make_profile(STUDENT_ID, role="student", campus_id=CAMPUS),
        FACULTY_ID: make_profile(FACULTY_ID, role="faculty", campus_id=CAMPUS),
        MANAGER_ID: make_profile(MANAGER_ID, role="management", campus_id=CAMPUS),
    }
    sb, ai = FakeSupabase(), FakeAI(reply="Pay in week two [1].")
    sb.tables["departments"].append({"id": str(uuid4()), "campus_id": CAMPUS, "name": "CS"})
    app.dependency_overrides[get_token_verifier] = lambda: _Verifier()
    app.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(profiles)
    app.dependency_overrides[get_supabase_client] = lambda: sb
    app.dependency_overrides[get_openai_client] = lambda: ai
    try:
        yield TestClient(app), sb, ai
    finally:
        app.dependency_overrides.clear()


def _auth(user_id):
    return {"Authorization": f"Bearer {user_id}"}


def test_upload_requires_a_signed_in_user(harness):
    client, _, _ = harness
    response = client.post(f"{API}/documents", data={"title": "x"},
                           files={"file": ("a.pdf", _pdf_bytes(), "application/pdf")})
    assert response.status_code == 401


def test_students_cannot_upload_documents(harness):
    client, sb, _ = harness
    response = client.post(f"{API}/documents", headers=_auth(STUDENT_ID), data={"title": "x"},
                           files={"file": ("a.pdf", _pdf_bytes(), "application/pdf")})
    assert response.status_code == 403
    assert sb.tables["documents"] == []


def test_faculty_upload_returns_a_ready_draft(harness):
    client, sb, _ = harness
    response = client.post(f"{API}/documents", headers=_auth(FACULTY_ID),
                           data={"title": "Fee Policy", "visibility": "public_students", "scope": "campus"},
                           files={"file": ("fee.pdf", _pdf_bytes(), "application/pdf")})

    assert response.status_code == 201
    body = response.json()
    assert body["processing_status"] == "ready"
    assert body["publication_status"] == "draft"
    assert body["title"] == "Fee Policy"
    assert "storage_path" not in body


def test_upload_rejects_unknown_visibility(harness):
    client, _, _ = harness
    response = client.post(f"{API}/documents", headers=_auth(FACULTY_ID),
                           data={"title": "x", "visibility": "everyone"},
                           files={"file": ("a.pdf", _pdf_bytes(), "application/pdf")})
    assert response.status_code == 422


def test_non_pdf_upload_returns_400_with_message(harness):
    client, _, _ = harness
    response = client.post(f"{API}/documents", headers=_auth(FACULTY_ID), data={"title": "x"},
                           files={"file": ("a.txt", b"hello", "text/plain")})
    assert response.status_code == 400
    assert response.json() == {"detail": "Only PDF uploads are supported"}


def test_student_chat_returns_answer_with_citation(harness):
    client, sb, _ = harness
    sb.rpc_rows = [{"chunk_id": str(uuid4()), "document_id": str(uuid4()), "title": "Fee Policy",
                    "page_number": 3, "content": "Pay in week two.", "similarity": 0.8}]

    response = client.post(f"{API}/chat/ask", headers=_auth(STUDENT_ID), json={"question": "When is the fee due?"})

    assert response.status_code == 200
    body = response.json()
    assert body["abstained"] is False
    assert body["citations"][0]["title"] == "Fee Policy"
    assert body["citations"][0]["page"] == 3
    assert body["escalation_available"] is False


def test_chat_abstains_and_offers_escalation_when_no_evidence(harness):
    client, sb, _ = harness
    sb.rpc_rows = []

    response = client.post(f"{API}/chat/ask", headers=_auth(STUDENT_ID), json={"question": "Ghost policy?"})

    body = response.json()
    assert body["abstained"] is True
    assert body["answer"] == ABSTAIN_MESSAGE
    assert body["citations"] == []
    assert body["escalation_available"] is True


def test_faculty_cannot_use_student_chat(harness):
    client, _, _ = harness
    response = client.post(f"{API}/chat/ask", headers=_auth(FACULTY_ID), json={"question": "x"})
    assert response.status_code == 403


def test_chat_question_length_is_validated(harness):
    client, _, _ = harness
    response = client.post(f"{API}/chat/ask", headers=_auth(STUDENT_ID), json={"question": "x" * 1001})
    assert response.status_code == 422


def test_students_cannot_update_tickets(harness):
    client, _, _ = harness
    response = client.patch(f"{API}/tickets/{uuid4()}", headers=_auth(STUDENT_ID), json={"reply": "hi"})
    assert response.status_code == 403


def test_ticket_update_needs_a_change(harness):
    client, _, _ = harness
    response = client.patch(f"{API}/tickets/{uuid4()}", headers=_auth(FACULTY_ID), json={})
    assert response.status_code == 422


def test_management_stats_are_forbidden_to_faculty(harness):
    client, _, _ = harness
    assert client.get(f"{API}/management/stats", headers=_auth(FACULTY_ID)).status_code == 403


def test_management_stats_return_aggregates(harness):
    client, _, _ = harness
    response = client.get(f"{API}/management/stats", headers=_auth(MANAGER_ID))
    assert response.status_code == 200
    body = response.json()
    assert body["total_tickets"] == 0
    assert body["resolution_rate"] is None


def test_upstream_database_error_is_hidden_behind_a_generic_message(harness):
    client, sb, _ = harness

    async def broken(*args, **kwargs):
        raise SupabaseError(500, "relation secret_internal_table does not exist")

    sb.select_as_user = broken
    response = client.get(f"{API}/tickets", headers=_auth(STUDENT_ID))

    assert response.status_code == 502
    assert response.json() == {"detail": "Database request failed"}
    assert "secret_internal_table" not in response.text


def test_announcements_list_for_students(harness):
    client, sb, _ = harness
    sb.tables["announcements"].append({
        "id": str(uuid4()), "title": "Library hours", "body": "Open late.", "category": "Library",
        "is_important": False, "audience": "all_students", "scope": "campus",
        "campus_id": CAMPUS, "created_at": "2026-11-01T10:00:00+00:00",
    })
    response = client.get(f"{API}/announcements", headers=_auth(STUDENT_ID))
    assert response.status_code == 200
    assert response.json()[0]["title"] == "Library hours"
