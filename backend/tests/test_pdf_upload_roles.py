"""PDF upload is limited to Faculty and Authority, the policy the deployed line runs. Management reads documents;
it does not upload them. Fixtures only."""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.middleware.auth import get_profile_repository, get_token_verifier
from app.services.providers import get_data_client
from tests.conftest import FakeProfileRepository, make_profile
from tests.fakes import FakeDataClient

CAMPUS = str(uuid4())
ROLES = {str(uuid4()): role for role in ["faculty", "authority", "management", "student"]}


class _Verifier:
    def verify(self, token):
        return UUID(token)


def _upload_as(user_id):
    profiles = {uid: make_profile(uid, role=role, campus_id=CAMPUS) for uid, role in ROLES.items()}
    app.dependency_overrides[get_token_verifier] = lambda: _Verifier()
    app.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(profiles)
    app.dependency_overrides[get_data_client] = lambda: FakeDataClient()
    try:
        return TestClient(app).post(
            f"{settings.api_v1_prefix}/documents",
            headers={"Authorization": f"Bearer {user_id}"},
            files={"file": ("FIXTURE.pdf", b"%PDF-1.4 fixture", "application/pdf")},
            data={"title": "FIXTURE policy", "visibility": "public_students", "scope": "campus", "category": "General"},
        )
    finally:
        app.dependency_overrides.clear()


def test_management_cannot_upload_a_pdf():
    management = next(uid for uid, role in ROLES.items() if role == "management")

    assert _upload_as(management).status_code == 403


def test_faculty_can_upload_a_pdf():
    faculty = next(uid for uid, role in ROLES.items() if role == "faculty")

    assert _upload_as(faculty).status_code == 202


def test_a_student_cannot_upload_a_pdf():
    student = next(uid for uid, role in ROLES.items() if role == "student")

    assert _upload_as(student).status_code == 403
