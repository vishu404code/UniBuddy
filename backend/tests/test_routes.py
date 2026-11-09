from uuid import uuid4

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.ai.rag import ABSTAIN_MESSAGE
from app.config import settings
from app.main import app
from app.middleware.auth import get_token_verifier, get_profile_repository
from app.services.providers import get_ai_client, get_data_client
from app.services.errors import DataServiceError
from tests.conftest import FakeProfileRepository, make_profile
from tests.fakes import FakeAI, FakeDataClient

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
    sb, ai = FakeDataClient(), FakeAI(reply="Pay in week two [1].")
    sb.tables["departments"].append({"id": str(uuid4()), "campus_id": CAMPUS, "name": "CS"})
    app.dependency_overrides[get_token_verifier] = lambda: _Verifier()
    app.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(profiles)
    app.dependency_overrides[get_data_client] = lambda: sb
    app.dependency_overrides[get_ai_client] = lambda: ai
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


def test_faculty_upload_is_accepted_and_queued(harness):
    client, sb, _ = harness
    response = client.post(f"{API}/documents", headers=_auth(FACULTY_ID),
                           data={"title": "Fee Policy", "visibility": "public_students", "scope": "campus"},
                           files={"file": ("fee.pdf", _pdf_bytes(), "application/pdf")})

    assert response.status_code == 202
    body = response.json()
    assert body["processing_status"] == "pending"
    assert body["publication_status"] == "draft"
    assert body["title"] == "Fee Policy"
    assert "storage_path" not in body
    assert response.headers["location"].endswith(f"/documents/{body['id']}")


def test_queued_upload_reports_that_ai_processing_waits_for_the_key(harness, monkeypatch):
    client, _, _ = harness
    monkeypatch.setattr(settings, "gemini_api_key", None)
    response = client.post(f"{API}/documents", headers=_auth(FACULTY_ID), data={"title": "x"},
                           files={"file": ("a.pdf", _pdf_bytes(), "application/pdf")})

    assert response.status_code == 202
    assert "AI service" in response.json()["processing_note"]


def test_document_list_is_paged_and_filtered(harness):
    client, sb, _ = harness
    for index in range(3):
        sb.tables["documents"].append({
            "id": str(uuid4()), "title": f"Doc {index}", "original_filename": None, "visibility": "public_students",
            "scope": "campus", "publication_status": "published", "processing_status": "ready",
            "page_count": 1, "campus_id": CAMPUS, "department_id": None, "replaces_document_id": None,
            "created_at": f"2026-11-0{index + 1}T10:00:00+00:00", "uploaded_by": FACULTY_ID,
        })
    sb.tables["documents"].append({
        "id": str(uuid4()), "title": "Pending", "original_filename": None, "visibility": "public_students",
        "scope": "campus", "publication_status": "draft", "processing_status": "pending", "page_count": None,
        "campus_id": CAMPUS, "department_id": None, "replaces_document_id": None,
        "created_at": "2026-11-09T10:00:00+00:00", "uploaded_by": FACULTY_ID,
    })

    page = client.get(f"{API}/documents?limit=2&offset=0", headers=_auth(STUDENT_ID)).json()
    ready = client.get(f"{API}/documents?processing_status=ready", headers=_auth(STUDENT_ID)).json()

    assert page["total"] == 4 and len(page["items"]) == 2 and page["limit"] == 2
    assert ready["total"] == 3


def test_list_limit_is_bounded(harness):
    client, _, _ = harness
    assert client.get(f"{API}/documents?limit=500", headers=_auth(STUDENT_ID)).status_code == 422


def test_publish_conflict_from_database_is_a_409(harness):
    client, sb, _ = harness
    doc_id = str(uuid4())
    sb.tables["documents"].append({
        "id": doc_id, "title": "x", "original_filename": None, "visibility": "public_students", "scope": "campus",
        "publication_status": "draft", "processing_status": "ready", "page_count": 1, "campus_id": CAMPUS,
        "department_id": None, "replaces_document_id": None, "created_at": "2026-11-01T10:00:00+00:00",
        "uploaded_by": FACULTY_ID, "storage_path": "x",
    })

    async def raise_not_publishable(function, payload):
        raise DataServiceError(400, '{"message":"document_not_publishable"}')

    sb.rpc_service = raise_not_publishable
    response = client.post(f"{API}/documents/{doc_id}/publish", headers=_auth(FACULTY_ID))

    assert response.status_code == 409


def test_staff_dashboard_is_limited_to_faculty_and_authority(harness):
    client, sb, _ = harness
    sb.rpc_responses["staff_dashboard_stats"] = {
        "open_tickets": 2, "resolved_tickets": 1, "tickets_by_status": {"submitted": 2},
        "unassigned_queue": 1, "assigned_to_me": 1, "avg_first_response_hours": 4.5,
        "by_department": [], "drafts_visible": 0, "published_visible": 0,
    }
    assert client.get(f"{API}/dashboard/staff", headers=_auth(STUDENT_ID)).status_code == 403
    response = client.get(f"{API}/dashboard/staff", headers=_auth(FACULTY_ID))
    assert response.status_code == 200
    assert response.json()["unassigned_queue"] == 1
    assert sb.rpc_calls[-1][1] == "staff_dashboard_stats"


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


def test_management_stats_return_database_aggregates(harness):
    client, sb, _ = harness
    sb.rpc_responses["management_ticket_stats"] = {
        "total_tickets": 3, "resolved_tickets": 1, "resolution_rate": 0.3333,
        "avg_first_response_hours": 5.0,
        "campuses": [{"id": CAMPUS, "name": "Campus 1", "total_tickets": 3, "resolved_tickets": 1,
                      "resolution_rate": 0.3333, "avg_first_response_hours": 5.0}],
        "departments": [], "generated_at": "2026-11-08T10:00:00+00:00",
    }
    response = client.get(f"{API}/management/stats", headers=_auth(MANAGER_ID))
    assert response.status_code == 200
    body = response.json()
    assert body["total_tickets"] == 3
    assert body["campuses"][0]["name"] == "Campus 1"
    assert "student_id" not in response.text


def test_upstream_database_error_is_hidden_behind_a_generic_message(harness):
    client, sb, _ = harness

    async def broken(*args, **kwargs):
        raise DataServiceError(500, "relation secret_internal_table does not exist")

    sb.select_as_user = broken
    response = client.get(f"{API}/tickets", headers=_auth(STUDENT_ID))

    assert response.status_code == 502
    assert response.json() == {"detail": "Database request failed."}
    assert "secret_internal_table" not in response.text
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
    assert response.json()["items"][0]["title"] == "Library hours"
    assert response.json()["total"] == 1
