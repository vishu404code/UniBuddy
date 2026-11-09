"""Google sign-in and sign-up, with the in-memory fake and an injected Google verifier.

No network calls. Google's verification is replaced by a function that returns claims.
"""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.session import read_session_token
from app.config import settings
from app.main import app
from app.middleware.auth import get_profile_repository, get_token_verifier
from app.repositories.profiles import ProfileRepository
from app.services.account_directory import AccountDirectory
from app.services.token_verifier import SessionTokenVerifier
from app.services.google_sign_in import GoogleSignInError, request_student_access, sign_in
from app.services.providers import get_google_verifier, get_data_client
from tests.fakes import FakeDataClient

CLIENT_ID = "stage2-test.apps.googleusercontent.com"
SECRET = "t" * 40
TOKEN = "x" * 30  # any non-empty token; the injected verifier decides what it means


def _verifier(subject="google-sub-1", email="Person@Example.com", verified=True, name="Person Example"):
    def verify(token, client_id):
        if token != TOKEN:
            raise ValueError("not a valid token")
        assert client_id == CLIENT_ID
        return {
            "iss": "https://accounts.google.com",
            "sub": subject,
            "aud": CLIENT_ID,
            "email": email,
            "email_verified": verified,
            "name": name,
        }

    return verify


def _account(sb, *, subject=None, email="person@example.com", with_profile=True, role="student"):
    account_id = str(uuid4())
    sb.tables.setdefault("account_identities", []).append(
        {"id": account_id, "email": email, "google_subject": subject}
    )
    if with_profile:
        sb.tables.setdefault("profiles", []).append(
            {"id": account_id, "email": email, "full_name": "P", "role": role,
             "campus_id": str(uuid4()), "department_id": None, "cross_campus_record_access": False}
        )
    return UUID(account_id)


async def _sign_in(sb, **kwargs):
    return await sign_in(sb=sb, id_token=TOKEN, client_id=CLIENT_ID, session_secret=SECRET,
                         verifier=kwargs.pop("verifier", _verifier()), **kwargs)


# --- sign-in ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unverified_google_email_is_refused_and_nothing_changes():
    sb = FakeDataClient()
    _account(sb)

    with pytest.raises(GoogleSignInError) as info:
        await _sign_in(sb, verifier=_verifier(verified=False))

    assert info.value.status_code == 401
    assert info.value.code == "google_unverified"


@pytest.mark.asyncio
async def test_linked_account_signs_in_and_the_token_carries_no_role():
    sb = FakeDataClient()
    account = _account(sb, subject="google-sub-1", role="authority")

    session = await _sign_in(sb)

    assert read_session_token(session["access_token"], SECRET) == account
    assert set(_decoded_claims(session["access_token"])) == {"sub", "iss", "aud", "iat", "exp"}


def _decoded_claims(token):
    import jwt

    return jwt.decode(token, SECRET, algorithms=["HS256"], audience="unibuddy-web", issuer="unibuddy-api")


@pytest.mark.asyncio
async def test_invited_profile_is_linked_on_first_google_sign_in_keeping_its_id():
    sb = FakeDataClient()
    account = _account(sb, subject=None, email="person@example.com", role="faculty")

    session = await _sign_in(sb, verifier=_verifier(subject="google-sub-new", email="person@example.com"))

    assert read_session_token(session["access_token"], SECRET) == account
    assert sb.tables["account_identities"][0]["google_subject"] == "google-sub-new"


@pytest.mark.asyncio
async def test_email_linked_to_another_google_account_is_a_conflict():
    sb = FakeDataClient()
    _account(sb, subject="owner-sub", email="person@example.com")

    with pytest.raises(GoogleSignInError) as info:
        await _sign_in(sb, verifier=_verifier(subject="attacker-sub", email="person@example.com"))

    assert info.value.status_code == 409
    assert sb.tables["account_identities"][0]["google_subject"] == "owner-sub"


@pytest.mark.asyncio
async def test_any_verified_domain_can_sign_in_once_it_has_a_profile():
    sb = FakeDataClient()
    account = _account(sb, subject="google-sub-1", email="person@gmail.com")

    session = await _sign_in(sb, verifier=_verifier(email="person@gmail.com"))

    assert read_session_token(session["access_token"], SECRET) == account


@pytest.mark.asyncio
async def test_sign_in_is_refused_when_google_is_not_configured():
    with pytest.raises(GoogleSignInError) as info:
        await sign_in(sb=FakeDataClient(), id_token=TOKEN, client_id=None, session_secret=SECRET, verifier=_verifier())

    assert info.value.status_code == 503


# --- sign-up as a Student request ------------------------------------------------------

@pytest.mark.asyncio
async def test_a_person_who_already_has_an_account_gets_no_new_request():
    sb = FakeDataClient()
    _account(sb, subject="google-sub-1", email="person@example.com")

    result = await request_student_access(sb=sb, id_token=TOKEN, client_id=CLIENT_ID, verifier=_verifier())

    assert result["status"] == "has_account"
    assert sb.tables.get("registration_requests", []) == []


# --- invitation accounts ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_invitation_creates_an_account_row_without_a_google_subject():
    sb = FakeDataClient()

    account_id = await AccountDirectory(sb).invite_user("Invitee@Example.com", "Invitee")

    row = sb.tables["account_identities"][0]
    assert row["id"] == str(account_id)
    assert row["email"] == "invitee@example.com"
    assert row.get("google_subject") is None


@pytest.mark.asyncio
async def test_retry_reuses_the_account_row_left_without_a_profile():
    sb = FakeDataClient()
    directory = AccountDirectory(sb)
    first = await directory.invite_user("invitee@example.com", "Invitee")

    second = await directory.invite_user("invitee@example.com", "Invitee")

    assert first == second
    assert len(sb.tables["account_identities"]) == 1


# --- routes ------------------------------------------------------------------------------

@pytest.fixture
def google_mode(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "session_secret", SECRET)
    sb = FakeDataClient()
    app.dependency_overrides[get_data_client] = lambda: sb
    app.dependency_overrides[get_google_verifier] = lambda: _verifier(email="person@example.com")
    app.dependency_overrides[get_profile_repository] = lambda: ProfileRepository(sb)
    app.dependency_overrides[get_token_verifier] = lambda: SessionTokenVerifier(SECRET)
    try:
        yield sb
    finally:
        app.dependency_overrides.clear()


def test_route_signs_in_and_me_returns_the_profile_role(google_mode):
    _account(google_mode, subject="google-sub-1", email="person@example.com", role="authority")
    client = TestClient(app)

    signed_in = client.post("/api/v1/auth/google", json={"id_token": TOKEN})
    assert signed_in.status_code == 200
    token = signed_in.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["role"] == "authority"


def test_route_rejects_extra_fields_so_the_client_cannot_send_a_role(google_mode):
    response = TestClient(app).post(
        "/api/v1/auth/google", json={"id_token": TOKEN, "role": "super_admin"}
    )

    assert response.status_code == 422


def test_route_with_a_bad_token_is_unauthorized(google_mode):
    response = TestClient(app).post("/api/v1/auth/google", json={"id_token": "y" * 30})

    assert response.status_code == 401


def test_me_with_a_token_for_a_removed_profile_is_forbidden(google_mode):
    from app.services.token_verifier import SessionTokenVerifier
    from app.auth.session import issue_session_token

    gone = uuid4()
    token = issue_session_token(gone, SECRET)

    response = TestClient(app).get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


# --- open Student signup (the policy: a verified person with no profile becomes a Student) -----

@pytest.mark.asyncio
async def test_new_google_account_becomes_a_student_with_no_campus():
    sb = FakeDataClient()

    session = await _sign_in(sb)

    profile = sb.tables["profiles"][0]
    assert profile["role"] == "student"
    assert profile["campus_id"] is None
    assert profile["department_id"] is None
    assert read_session_token(session["access_token"], SECRET) == UUID(profile["id"])
    assert sb.tables["account_identities"][0]["google_subject"] == "google-sub-1"


@pytest.mark.asyncio
async def test_account_row_without_a_profile_becomes_a_student_and_is_linked():
    sb = FakeDataClient()
    _account(sb, subject=None, email="person@example.com", with_profile=False)

    await _sign_in(sb, verifier=_verifier(subject="google-sub-1", email="person@example.com"))

    assert sb.tables["profiles"][0]["role"] == "student"
    assert sb.tables["account_identities"][0]["google_subject"] == "google-sub-1"


@pytest.mark.asyncio
async def test_open_signup_never_grants_a_privileged_role():
    sb = FakeDataClient()
    _account(sb, subject=None, email="staff@example.com", with_profile=False)

    await _sign_in(sb, verifier=_verifier(subject="google-sub-9", email="staff@example.com", name="Staff"))

    assert {row["role"] for row in sb.tables["profiles"]} == {"student"}


@pytest.mark.asyncio
async def test_access_request_creates_the_student_account_and_no_pending_row():
    sb = FakeDataClient()

    receipt = await request_student_access(sb=sb, id_token=TOKEN, client_id=CLIENT_ID,
                                           verifier=_verifier(email="New.Student@Gmail.com", name="New Student"))

    assert receipt["status"] == "has_account"
    assert sb.tables.get("registration_requests", []) == []
    assert sb.tables["profiles"][0]["email"] == "new.student@gmail.com"
    assert sb.tables["profiles"][0]["role"] == "student"


@pytest.mark.asyncio
async def test_repeat_access_request_does_not_create_a_second_account():
    sb = FakeDataClient()
    for _ in range(2):
        await request_student_access(sb=sb, id_token=TOKEN, client_id=CLIENT_ID, verifier=_verifier())

    assert len(sb.tables["profiles"]) == 1
    assert len(sb.tables["account_identities"]) == 1


def test_route_creates_a_student_for_a_new_google_person(google_mode):
    response = TestClient(app).post("/api/v1/auth/google", json={"id_token": TOKEN})

    assert response.status_code == 200
    token = response.json()["access_token"]
    me = TestClient(app).get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["role"] == "student"
    assert me.json()["campus_id"] is None



@pytest.mark.asyncio
async def test_new_student_gets_the_only_existing_campus():
    sb = FakeDataClient()
    campus_id = str(uuid4())
    sb.tables["campuses"] = [{"id": campus_id, "name": "Only Campus", "code": "only"}]

    await _sign_in(sb)

    profile = sb.tables["profiles"][0]
    assert profile["role"] == "student"
    assert str(profile["campus_id"]) == campus_id
    assert profile["department_id"] is None


@pytest.mark.asyncio
async def test_new_student_stays_unassigned_when_several_campuses_exist():
    sb = FakeDataClient()
    sb.tables["campuses"] = [
        {"id": str(uuid4()), "name": "Campus A", "code": "a"},
        {"id": str(uuid4()), "name": "Campus B", "code": "b"},
    ]

    await _sign_in(sb)

    assert sb.tables["profiles"][0]["campus_id"] is None
