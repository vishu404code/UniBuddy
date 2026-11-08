"""Google sign-in is only an identity check. Access and role come from the UniBuddy profile
for the Auth user ID, never from the email, the provider or user metadata in the token."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.middleware.auth import get_profile_repository, get_token_verifier
from tests.conftest import FakeProfileRepository, make_profile

ME_URL = f"{settings.api_v1_prefix}/auth/me"
USER_ID = "66666666-6666-6666-6666-666666666666"
OTHER_ID = "77777777-7777-7777-7777-777777777777"
CAMPUS_ID = "55555555-5555-5555-5555-555555555555"
DEPARTMENT_ID = "88888888-8888-8888-8888-888888888888"

GOOGLE_CLAIMS = {
    "email": "someone@nst.rishihood.edu.in",
    "app_metadata": {"provider": "google", "providers": ["google"]},
    "user_metadata": {"role": "super_admin", "campus_id": CAMPUS_ID, "full_name": "Claimed"},
}


@pytest.fixture
def client_for(verifier):
    def build(profiles):
        app.dependency_overrides[get_token_verifier] = lambda: verifier
        app.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(profiles)
        return TestClient(app)

    yield build
    app.dependency_overrides.clear()


def test_google_identity_with_no_profile_gets_no_access(client_for, make_token):
    client = client_for({})
    token = make_token(USER_ID, extra_claims=GOOGLE_CLAIMS)

    response = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


def test_matching_email_on_another_profile_does_not_grant_access(client_for, make_token):
    # A profile with the same email but a different Auth user ID must not be picked up.
    client = client_for({OTHER_ID: make_profile(OTHER_ID, role="authority", campus_id=CAMPUS_ID)})
    token = make_token(USER_ID, extra_claims=GOOGLE_CLAIMS)

    response = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("role", "campus_id", "department_id"),
    [
        ("student", CAMPUS_ID, DEPARTMENT_ID),
        ("faculty", CAMPUS_ID, DEPARTMENT_ID),
        ("authority", CAMPUS_ID, None),
        ("management", None, None),
        ("super_admin", None, None),
    ],
)
def test_each_role_comes_from_the_profile_whatever_the_token_claims(
    client_for, make_token, role, campus_id, department_id
):
    profile = make_profile(
        USER_ID, role=role, campus_id=campus_id, department_id=department_id
    )
    client = client_for({USER_ID: profile})
    # The token claims a different role and campus; they must be ignored.
    token = make_token(USER_ID, extra_claims=GOOGLE_CLAIMS)

    response = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == USER_ID
    assert body["role"] == role
    assert body["campus_id"] == campus_id
    assert body["department_id"] == department_id
