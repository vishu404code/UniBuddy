from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.middleware.auth import get_profile_repository, get_token_verifier
from app.services.providers import get_ai_client, get_data_client
from tests.conftest import FakeProfileRepository, make_profile
from tests.fakes import FakeAI, FakeDataClient

API = settings.api_v1_prefix
CAMPUS = str(uuid4())
STUDENT_ID = str(uuid4())
FACULTY_ID = str(uuid4())
MANAGER_ID = str(uuid4())
AUTHORITY_ID = str(uuid4())


class _Verifier:
    def verify(self, token):
        import uuid

        return uuid.UUID(token)


@pytest.fixture
def km_harness():
    profiles = {
        STUDENT_ID: make_profile(STUDENT_ID, role="student", campus_id=CAMPUS),
        FACULTY_ID: make_profile(FACULTY_ID, role="faculty", campus_id=CAMPUS),
        MANAGER_ID: make_profile(MANAGER_ID, role="management", campus_id=CAMPUS),
        AUTHORITY_ID: make_profile(AUTHORITY_ID, role="authority", campus_id=CAMPUS),
    }
    sb, ai = FakeDataClient(), FakeAI(reply="Answer with source [1].")
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


def test_management_can_create_text_content(km_harness):
    client, sb, _ = km_harness
    payload = {
        "title": "Attendance Policy 2026",
        "content": "Students must maintain at least 75% attendance in all courses.",
        "category": "Academic Policy",
        "scope": "campus",
        "visibility": "public_students",
        "publication_status": "draft",
    }
    res = client.post(f"{API}/documents/content", headers=_auth(MANAGER_ID), json=payload)
    assert res.status_code == 202
    data = res.json()
    assert data["title"] == "Attendance Policy 2026"
    assert data["item_type"] == "text_content"
    assert data["publication_status"] == "draft"


def test_student_cannot_create_text_content(km_harness):
    client, _, _ = km_harness
    payload = {
        "title": "Hacked Policy",
        "content": "No attendance required.",
        "category": "Academic Policy",
    }
    res = client.post(f"{API}/documents/content", headers=_auth(STUDENT_ID), json=payload)
    assert res.status_code == 403


def test_management_can_update_text_content(km_harness):
    client, sb, _ = km_harness
    create_res = client.post(
        f"{API}/documents/content",
        headers=_auth(MANAGER_ID),
        json={"title": "Hostel Code", "content": "Initial rules.", "category": "Hostel"},
    )
    assert create_res.status_code == 202
    doc_id = create_res.json()["id"]

    patch_res = client.patch(
        f"{API}/documents/content/{doc_id}",
        headers=_auth(MANAGER_ID),
        json={"content": "Updated curfew is 10 PM.", "publication_status": "published"},
    )
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["publication_status"] == "published"


def test_management_can_delete_document(km_harness):
    client, sb, _ = km_harness
    create_res = client.post(
        f"{API}/documents/content",
        headers=_auth(MANAGER_ID),
        json={"title": "Temporary Note", "content": "Note content.", "category": "General"},
    )
    doc_id = create_res.json()["id"]

    del_res = client.delete(f"{API}/documents/{doc_id}", headers=_auth(MANAGER_ID))
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    get_res = client.get(f"{API}/documents/{doc_id}", headers=_auth(MANAGER_ID))
    assert get_res.status_code == 404


def test_knowledge_stats_overview(km_harness):
    client, sb, _ = km_harness
    client.post(
        f"{API}/documents/content",
        headers=_auth(MANAGER_ID),
        json={"title": "Doc 1", "content": "Content 1", "publication_status": "draft"},
    )
    res = client.get(f"{API}/documents/stats/overview", headers=_auth(MANAGER_ID))
    assert res.status_code == 200
    stats = res.json()
    assert stats["total_items"] >= 1
    assert stats["total_text_content"] >= 1


def test_health_services_diagnostics(km_harness):
    client, _, _ = km_harness
    res = client.get(f"{API}/health/services")
    assert res.status_code == 200
    data = res.json()
    assert "services" in data
    assert "database" in data["services"]
    assert "gemini_ai" in data["services"]

