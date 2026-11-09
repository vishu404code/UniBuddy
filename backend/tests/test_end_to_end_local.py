"""End-to-end routes on the local PostgreSQL database, with the real Postgres client and row rules.

Only the outside services are replaced: Google (fake verifier), Gemini (fake AI) and R2 (in-memory
store). Needs TEST_DATABASE_URL, pointing at a local database that has the schema applied (the SQL
runner builds it). Each test uses unique IDs. Skipped without the variable.
"""

import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.auth.session import issue_session_token
from app.config import settings
from app.main import app
from app.middleware.auth import get_profile_repository, get_token_verifier
from app.repositories.profiles import ProfileRepository
from app.services.postgres_client import PostgresClient
from app.services.providers import get_ai_client, get_data_client, get_google_verifier
from app.services.token_verifier import SessionTokenVerifier
from tests.fakes import FakeAI
from tests.test_storage_stage1 import MemoryStore

DSN = os.environ.get("TEST_DATABASE_URL")
SECRET = "e2e-test-session-secret-with-more-than-32-characters"
CLIENT_ID = "e2e-test.apps.googleusercontent.com"
API = settings.api_v1_prefix
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL is not set")


def _owner(sql, params=()):
    with psycopg.connect(DSN) as conn:
        conn.execute(sql, params)
        conn.commit()


def _owner_one(sql, params=()):
    with psycopg.connect(DSN) as conn:
        return conn.execute(sql, params).fetchone()


def _seed_campus_with_users():
    code = f"e2e-{uuid4().hex[:10]}"
    campus_id = uuid4()
    _owner("insert into public.campuses (id, name, code) values (%s, %s, %s)", (campus_id, f"E2E {code}", code))
    student_id, authority_id = uuid4(), uuid4()
    for user_id, role in ((student_id, "student"), (authority_id, "authority")):
        email = f"{user_id.hex}@example.test"
        _owner("insert into public.account_identities (id, email, google_subject) values (%s, %s, %s)",
               (user_id, email, f"sub-{user_id.hex}"))
        _owner("insert into public.profiles (id, email, role, campus_id) values (%s, %s, %s, %s)",
               (user_id, email, role, campus_id))
    return campus_id, student_id, authority_id


def _seed_document(campus_id, uploader, title, publication):
    doc_id = uuid4()
    key = f"{campus_id}/{doc_id}.pdf"
    _owner(
        "insert into public.documents (id, title, storage_path, uploaded_by, campus_id, scope, visibility, "
        "processing_status, publication_status, page_count) "
        "values (%s, %s, %s, %s, %s, 'campus', 'public_students', 'ready', %s, 1)",
        (doc_id, title, key, uploader, campus_id, publication),
    )
    return doc_id


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "session_secret", SECRET)
    monkeypatch.setattr(settings, "google_client_id", CLIENT_ID)
    pg = PostgresClient(DSN, SECRET, object_store=MemoryStore())
    app.dependency_overrides[get_data_client] = lambda: pg
    app.dependency_overrides[get_profile_repository] = lambda: ProfileRepository(pg)
    app.dependency_overrides[get_token_verifier] = lambda: SessionTokenVerifier(SECRET)
    app.dependency_overrides[get_ai_client] = lambda: FakeAI(reply="Pay in week two [1].")
    app.dependency_overrides[get_google_verifier] = lambda: (
        lambda token, client_id: {
            "iss": "https://accounts.google.com", "sub": "sub-e2e-linked", "aud": client_id,
            "email": "linked.e2e@example.test", "email_verified": True, "name": "Linked E2E",
        }
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _auth(user_id):
    return {"Authorization": f"Bearer {issue_session_token(user_id, SECRET)}"}


def test_me_returns_the_role_from_the_profile_row(client):
    campus, student, _ = _seed_campus_with_users()

    response = client.get(f"{API}/auth/me", headers=_auth(student))

    assert response.status_code == 200
    assert response.json()["role"] == "student"
    assert response.json()["campus_id"] == str(campus)


def test_no_token_and_forged_token_are_refused(client):
    assert client.get(f"{API}/auth/me").status_code == 401
    forged = issue_session_token(uuid4(), "x" * 40)
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_student_lists_only_published_documents_of_their_campus(client):
    campus, student, authority = _seed_campus_with_users()
    published = _seed_document(campus, authority, "E2E published", "published")
    _seed_document(campus, authority, "E2E draft", "draft")
    other_campus, _, other_authority = _seed_campus_with_users()
    _seed_document(other_campus, other_authority, "E2E other campus", "published")

    response = client.get(f"{API}/documents", headers=_auth(student))

    assert response.status_code == 200
    titles = [row["title"] for row in response.json()["items"]]
    assert titles == ["E2E published"]
    assert str(published) in [row["id"] for row in response.json()["items"]]


def test_document_detail_of_another_campus_is_not_found(client):
    campus, student, authority = _seed_campus_with_users()
    other_campus, _, other_authority = _seed_campus_with_users()
    hidden = _seed_document(other_campus, other_authority, "E2E hidden", "published")

    response = client.get(f"{API}/documents/{hidden}", headers=_auth(student))

    assert response.status_code == 404


def test_student_has_no_tickets_on_a_fresh_account(client):
    _, student, _ = _seed_campus_with_users()

    response = client.get(f"{API}/tickets", headers=_auth(student))

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_google_sign_in_links_an_existing_profile_and_returns_a_session(client):
    token_id = uuid4().hex
    email = f"linked-{token_id}@example.test"
    subject = f"sub-linked-{token_id}"
    campus = uuid4()
    _owner("insert into public.campuses (id, name, code) values (%s, %s, %s)",
           (campus, f"E2E link {campus.hex[:6]}", f"link-{campus.hex[:10]}"))
    account = uuid4()
    _owner("insert into public.account_identities (id, email) values (%s, %s)", (account, email))
    _owner("insert into public.profiles (id, email, role, campus_id) values (%s, %s, 'faculty', %s)",
           (account, email, campus))
    app.dependency_overrides[get_google_verifier] = lambda: (
        lambda token, client_id: {
            "iss": "https://accounts.google.com", "sub": subject, "aud": client_id,
            "email": email, "email_verified": True, "name": "Linked E2E",
        }
    )

    signed_in = client.post(f"{API}/auth/google", json={"id_token": "x" * 30})

    assert signed_in.status_code == 200
    token = signed_in.json()["access_token"]
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["role"] == "faculty"
    assert me.json()["id"] == str(account)
    linked = _owner_one("select google_subject from public.account_identities where id = %s", (account,))
    assert linked[0] == subject


def test_unknown_google_person_gets_no_session_and_no_role(client):
    stranger = uuid4().hex
    app.dependency_overrides[get_google_verifier] = lambda: (
        lambda token, client_id: {
            "iss": "https://accounts.google.com", "sub": f"stranger-{stranger}", "aud": client_id,
            "email": f"stranger-{stranger}@example.test", "email_verified": True, "name": "Stranger",
        }
    )

    response = client.post(f"{API}/auth/google", json={"id_token": "x" * 30})

    assert response.status_code == 403
    assert "access_token" not in response.json()
