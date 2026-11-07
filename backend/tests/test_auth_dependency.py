from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.middleware.auth import get_profile_repository, get_token_verifier, require_roles
from app.main import app
from app.schemas.auth import CurrentUser
from tests.conftest import FakeProfileRepository, make_profile

STUDENT_ID = "22222222-2222-2222-2222-222222222222"
FACULTY_ID = "33333333-3333-3333-3333-333333333333"
ORPHAN_ID = "44444444-4444-4444-4444-444444444444"
CAMPUS_ID = "55555555-5555-5555-5555-555555555555"
ME_URL = f"{settings.api_v1_prefix}/auth/me"


def _use_fakes(verifier, profiles: dict[str, CurrentUser]):
    app.dependency_overrides[get_token_verifier] = lambda: verifier
    app.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(profiles)


def _clear_overrides():
    app.dependency_overrides.clear()


def test_me_requires_authorization_header(verifier):
    _use_fakes(verifier, {})
    try:
        response = TestClient(app).get(ME_URL)
    finally:
        _clear_overrides()

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_rejects_invalid_token(verifier):
    _use_fakes(verifier, {})
    try:
        response = TestClient(app).get(ME_URL, headers={"Authorization": "Bearer nonsense"})
    finally:
        _clear_overrides()

    assert response.status_code == 401


def test_me_rejects_non_bearer_scheme(verifier, make_token):
    _use_fakes(verifier, {})
    try:
        token = make_token(STUDENT_ID)
        response = TestClient(app).get(ME_URL, headers={"Authorization": f"Basic {token}"})
    finally:
        _clear_overrides()

    assert response.status_code == 401


def test_valid_token_without_profile_is_forbidden(verifier, make_token):
    _use_fakes(verifier, {})
    try:
        token = make_token(ORPHAN_ID)
        response = TestClient(app).get(ME_URL, headers={"Authorization": f"Bearer {token}"})
    finally:
        _clear_overrides()

    assert response.status_code == 403


def test_me_returns_profile_role_and_campus(verifier, make_token):
    profiles = {STUDENT_ID: make_profile(STUDENT_ID, role="student", campus_id=CAMPUS_ID)}
    _use_fakes(verifier, profiles)
    try:
        token = make_token(STUDENT_ID)
        response = TestClient(app).get(ME_URL, headers={"Authorization": f"Bearer {token}"})
    finally:
        _clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == STUDENT_ID
    assert body["role"] == "student"
    assert body["campus_id"] == CAMPUS_ID


def test_role_comes_from_profile_not_token_claims(verifier, make_token):
    profiles = {STUDENT_ID: make_profile(STUDENT_ID, role="student")}
    _use_fakes(verifier, profiles)
    try:
        token = make_token(STUDENT_ID, extra_claims={"user_metadata": {"role": "management"}})
        response = TestClient(app).get(ME_URL, headers={"Authorization": f"Bearer {token}"})
    finally:
        _clear_overrides()

    assert response.status_code == 200
    assert response.json()["role"] == "student"


def _role_guarded_client(verifier, profiles: dict[str, CurrentUser]) -> TestClient:
    guarded = FastAPI()

    @guarded.get("/faculty-only")
    async def faculty_only(user: CurrentUser = Depends(require_roles("faculty"))):
        return {"ok": True, "id": str(user.id)}

    guarded.dependency_overrides[get_token_verifier] = lambda: verifier
    guarded.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(profiles)
    return TestClient(guarded)


def test_require_roles_allows_matching_role(verifier, make_token):
    profiles = {FACULTY_ID: make_profile(FACULTY_ID, role="faculty")}
    client = _role_guarded_client(verifier, profiles)

    response = client.get("/faculty-only", headers={"Authorization": f"Bearer {make_token(FACULTY_ID)}"})

    assert response.status_code == 200


def test_require_roles_blocks_other_roles(verifier, make_token):
    profiles = {STUDENT_ID: make_profile(STUDENT_ID, role="student")}
    client = _role_guarded_client(verifier, profiles)

    response = client.get("/faculty-only", headers={"Authorization": f"Bearer {make_token(STUDENT_ID)}"})

    assert response.status_code == 403
