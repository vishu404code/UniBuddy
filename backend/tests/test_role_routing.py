"""Role routing from Google sign-in to the role each API route enforces.

Fixtures only: every account here is an in-memory row created by this file. The Google token
verifier is replaced by a function that returns claims. No network calls, no real account, no real
session. The chain tested is: verified Google identity -> UniBuddy profile (by account ID) ->
session token -> GET /auth/me -> the role each route checks.

The profile row is the source of truth. A token, an email address or a Google claim never sets a role.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.middleware.auth import get_profile_repository, get_token_verifier
from app.repositories.profiles import ProfileRepository
from app.services.providers import get_data_client, get_google_verifier
from app.services.token_verifier import SessionTokenVerifier
from tests.fakes import FakeDataClient

CLIENT_ID = "role-routing-fixture.apps.googleusercontent.com"
SECRET = "r" * 40
TOKEN = "g" * 30
API = settings.api_v1_prefix
CAMPUS = "c0000000-0000-4000-8000-000000000001"

# The documented pre-authorized Faculty email (services/google_sign_in.py PREAUTHORIZED_ACCOUNTS).
FACULTY_EMAIL = "tarun.s26366@nst.rishihood.edu.in"


def _claims(subject, email):
    return {"iss": "https://accounts.google.com", "sub": subject, "aud": CLIENT_ID,
            "email": email, "email_verified": True, "name": "Fixture Person"}


def _verifier_for(subject, email):
    def verify(token, client_id):
        assert token == TOKEN
        return _claims(subject, email)

    return verify


def _account(sb, *, email, role, subject=None, campus=CAMPUS):
    account_id = str(uuid4())
    sb.tables["account_identities"].append({"id": account_id, "email": email, "google_subject": subject})
    sb.tables["profiles"].append({
        "id": account_id, "email": email, "full_name": "Fixture Person", "role": role,
        "campus_id": campus if role != "management" else None, "department_id": None,
        "cross_campus_record_access": False,
    })
    return account_id


@pytest.fixture
def harness(monkeypatch):
    """Runs the real routes with the in-memory data client and a fixture Google verifier."""
    monkeypatch.setattr(settings, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "session_secret", SECRET)
    sb = FakeDataClient()
    sb.tables["campuses"].append({"id": CAMPUS, "name": "Rishihood University, Sonipat", "code": "sonipat"})

    def use(subject, email):
        app.dependency_overrides[get_google_verifier] = lambda: _verifier_for(subject, email)
        return TestClient(app)

    app.dependency_overrides[get_data_client] = lambda: sb
    app.dependency_overrides[get_profile_repository] = lambda: ProfileRepository(sb)
    app.dependency_overrides[get_token_verifier] = lambda: SessionTokenVerifier(SECRET)
    try:
        yield sb, use
    finally:
        app.dependency_overrides.clear()


def _sign_in_and_me(client):
    signed_in = client.post(f"{API}/auth/google", json={"id_token": TOKEN})
    assert signed_in.status_code == 200, signed_in.text
    token = signed_in.json()["access_token"]
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me


# --- Sign-in lands on the role the profile holds ------------------------------------------------

@pytest.mark.parametrize("role", ["student", "faculty", "authority", "management"])
def test_a_linked_account_gets_its_profile_role_after_sign_in(harness, role):
    sb, use = harness
    subject, email = f"sub-{role}", f"{role}@fixture.invalid"
    _account(sb, email=email, role=role, subject=subject)

    token, me = _sign_in_and_me(use(subject, email))

    assert me.status_code == 200
    assert me.json()["role"] == role


def test_an_authority_account_that_has_not_linked_yet_keeps_its_authority_role(harness):
    """Email match on a profile with no Google subject yet: the sign-in links it and keeps its role."""
    sb, use = harness
    email = "authority-unlinked@fixture.invalid"
    _account(sb, email=email, role="authority", subject=None)

    _, me = _sign_in_and_me(use("sub-new-authority", email))

    assert me.status_code == 200
    assert me.json()["role"] == "authority"
    assert sb.tables["profiles"][0]["role"] == "authority"
    assert len(sb.tables["profiles"]) == 1  # no second, Student profile


def test_the_documented_faculty_email_gets_faculty_on_first_sign_in_never_student(harness):
    sb, use = harness

    _, me = _sign_in_and_me(use("sub-faculty-first", FACULTY_EMAIL))

    assert me.status_code == 200
    assert me.json()["role"] == "faculty"
    assert [p["role"] for p in sb.tables["profiles"]] == ["faculty"]


def test_an_unknown_verified_email_becomes_a_student_and_nothing_else(harness):
    sb, use = harness

    _, me = _sign_in_and_me(use("sub-stranger", "stranger@fixture.invalid"))

    assert me.status_code == 200
    assert me.json()["role"] == "student"


def test_a_role_word_in_the_email_does_not_grant_a_role(harness):
    sb, use = harness
    for email in ("authority.office@fixture.invalid", "management.desk@fixture.invalid", "faculty.x@fixture.invalid"):
        _, me = _sign_in_and_me(use(f"sub-{email}", email))
        assert me.json()["role"] == "student", email


# --- Each route only serves its own roles -------------------------------------------------------

def _token_for(sb, use, role):
    subject, email = f"route-{role}", f"route-{role}@fixture.invalid"
    _account(sb, email=email, role=role, subject=subject)
    token, _ = _sign_in_and_me(use(subject, email))
    return token


def _stub_management_analytics(monkeypatch):
    now = datetime(2026, 11, 18, tzinfo=timezone.utc)

    async def fake(_sb):
        return {
            "questions_total": 0, "questions_by_day": [], "tickets_by_day": [],
            "gemini": {"operation": "answer", "first_recorded_at": None, "last_recorded_at": None,
                       "rows_recorded": 0, "requests": 0, "rows_with_input_tokens": 0,
                       "rows_with_output_tokens": 0, "input_tokens": None, "output_tokens": None, "models": []},
            "ticket_totals": {"total_tickets": 0, "resolved_tickets": 0, "resolution_rate": None,
                              "avg_first_response_hours": None, "campuses": [], "departments": [],
                              "generated_at": now},
            "generated_at": now,
        }

    monkeypatch.setattr("app.routes.dashboards.management_analytics", fake)


@pytest.mark.parametrize("role", ["student", "faculty", "authority"])
def test_management_analytics_refuses_every_other_role(harness, monkeypatch, role):
    sb, use = harness
    _stub_management_analytics(monkeypatch)
    token = _token_for(sb, use, role)

    response = TestClient(app).get(f"{API}/management/analytics", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


def test_management_analytics_serves_the_management_role(harness, monkeypatch):
    sb, use = harness
    _stub_management_analytics(monkeypatch)
    token = _token_for(sb, use, "management")

    response = TestClient(app).get(f"{API}/management/analytics", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["questions_total"] == 0


@pytest.mark.parametrize("role,path,allowed", [
    ("student", "/dashboard/student", True),
    ("faculty", "/dashboard/student", False),
    ("authority", "/dashboard/student", False),
    ("management", "/dashboard/student", False),
    ("faculty", "/dashboard/staff", True),
    ("authority", "/dashboard/staff", True),
    ("student", "/dashboard/staff", False),
    ("management", "/dashboard/staff", False),
])
def test_dashboards_serve_only_their_roles(harness, role, path, allowed):
    sb, use = harness
    token = _token_for(sb, use, role)

    # The dashboard bodies are not what this test checks. Only whether the role is refused is checked,
    # so server-side errors from the stubbed database are not raised into the test.
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(f"{API}{path}", headers={"Authorization": f"Bearer {token}"})

    if allowed:
        assert response.status_code != 403
    else:
        assert response.status_code == 403


def test_a_token_for_a_removed_profile_is_refused_not_downgraded(harness):
    sb, use = harness
    token, _ = _sign_in_and_me(use("sub-gone", "gone@fixture.invalid"))
    sb.tables["profiles"].clear()

    response = TestClient(app).get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
