from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.middleware.auth import get_profile_repository, get_token_verifier
from app.services.providers import get_supabase_client
from tests.conftest import FakeProfileRepository, make_profile
from tests.fakes import FakeSupabase

CAMPUS_A = str(uuid4())
CAMPUS_B = str(uuid4())
STUDENT = str(uuid4())
MANAGER = str(uuid4())


class _Verifier:
    def verify(self, token):
        import uuid
        return uuid.UUID(token)


def _client(sb):
    profiles = {
        STUDENT: make_profile(STUDENT, role="student", campus_id=CAMPUS_A),
        MANAGER: make_profile(MANAGER, role="management", campus_id=CAMPUS_A),
    }
    app.dependency_overrides[get_token_verifier] = lambda: _Verifier()
    app.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(profiles)
    app.dependency_overrides[get_supabase_client] = lambda: sb
    return TestClient(app)


def test_student_sees_only_departments_on_their_campus():
    sb = FakeSupabase()
    sb.tables["departments"] += [
        {"id": str(uuid4()), "campus_id": CAMPUS_A, "name": "Computer Science"},
        {"id": str(uuid4()), "campus_id": CAMPUS_B, "name": "Elsewhere"},
    ]
    try:
        response = _client(sb).get(f"{settings.api_v1_prefix}/departments", headers={"Authorization": f"Bearer {STUDENT}"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [d["name"] for d in response.json()] == ["Computer Science"]


def test_management_cannot_list_departments_here():
    sb = FakeSupabase()
    try:
        response = _client(sb).get(f"{settings.api_v1_prefix}/departments", headers={"Authorization": f"Bearer {MANAGER}"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403
