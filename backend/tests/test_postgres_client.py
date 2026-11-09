"""The Postgres data client against the local ported database. Run after
tests/sql/run_portable_db_tests.sh, with TEST_DATABASE_URL set to that database.

Fixtures are created directly with the local owner connection, because the backend's
service role deliberately cannot insert campuses or profiles. The tests then exercise
the client the way the backend uses it. Each test uses unique IDs and codes.
Without TEST_DATABASE_URL these tests are skipped.
"""

import asyncio
import os
from uuid import uuid4

import psycopg
import pytest

from app.auth.session import issue_session_token
from app.services.errors import DataServiceError
from app.services.postgres_client import PostgresClient
from tests.test_storage_stage1 import MemoryStore

DSN = os.environ.get("TEST_DATABASE_URL")
SECRET = "s" * 40
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL is not set")


@pytest.fixture
def client():
    return PostgresClient(DSN, SECRET, object_store=MemoryStore())


def _run(coro):
    return asyncio.run(coro)


def _owner(sql, params=()):
    """Test fixtures only: the owner connection bypasses the service grants on purpose."""
    with psycopg.connect(DSN) as conn:
        conn.execute(sql, params)
        conn.commit()


def _owner_rows(sql, params=()):
    with psycopg.connect(DSN) as conn:
        return conn.execute(sql, params).fetchall()


def _campus(name=None, code=None):
    code = code or f"pg-{uuid4().hex[:12]}"
    name = name or f"Campus {code}"
    _owner("insert into public.campuses (name, code) values (%s, %s)", (name, code))
    return {"name": name, "code": code, "id": _owner_rows("select id from public.campuses where code = %s", (code,))[0][0]}


def _profile(role="student", campus_id=None):
    user_id = uuid4()
    email = f"{user_id.hex}@example.test"
    _owner("insert into public.account_identities (id, email) values (%s, %s)", (user_id, email))
    _owner(
        "insert into public.profiles (id, email, role, campus_id) values (%s, %s, %s, %s)",
        (user_id, email, role, campus_id),
    )
    return user_id


# --- filters, ordering and paging --------------------------------------------------

def test_select_with_eq_in_and_null_filters(client):
    first = _campus()
    second = _campus()

    by_code = _run(client.select_service("campuses", {"select": "id,code", "code": f"eq.{first['code']}"}))
    by_list = _run(client.select_service("campuses", {"select": "id", "code": f"in.({first['code']},{second['code']})"}))
    none_null = _run(client.select_service("campuses", {"select": "id", "code": f"eq.{second['code']}", "name": "is.null"}))

    assert [row["id"] for row in by_code] == [first["id"]]
    assert len(by_list) == 2
    assert none_null == []


def test_order_and_limit(client):
    prefix = f"ord-{uuid4().hex[:8]}"
    for letter in ("b", "a", "c"):
        _campus(name=f"{prefix} {letter}", code=f"{prefix}-{letter}")

    rows = _run(client.select_service(
        "campuses",
        {"select": "name", "code": f"in.({prefix}-a,{prefix}-b,{prefix}-c)", "order": "name.desc", "limit": "2"},
    ))

    assert [row["name"].split()[-1] for row in rows] == ["c", "b"]


def test_neq_excludes_the_named_value(client):
    keep = _campus()
    drop = _campus()

    rows = _run(client.select_service(
        "campuses", {"select": "code", "code": f"in.({keep['code']},{drop['code']})", "name": f"neq.{drop['name']}"}
    ))

    assert [row["code"] for row in rows] == [keep["code"]]


@pytest.mark.parametrize(
    "params",
    [
        {"select": "id; drop table campuses"},
        {"select": "id", "code": "eq.x", "order": "name.sideways"},
        {"select": "id", "code": "like.x%"},
        {"select": "id", "code": "eq.x", "limit": "ten"},
        {"select": "id", "bad-column": "eq.x"},
    ],
)
def test_unsafe_or_unsupported_parameters_are_refused(client, params):
    with pytest.raises(DataServiceError) as info:
        _run(client.select_service("campuses", params))

    assert info.value.status_code == 400


# --- writes and grants ----------------------------------------------------------------

def test_service_insert_then_read_back(client):
    user_id = uuid4()
    _run(client.insert_service("account_identities", [{"id": str(user_id), "email": f"{user_id.hex}@example.test"}]))

    rows = _run(client.select_service("account_identities", {"select": "id", "id": f"eq.{user_id}"}))

    assert [row["id"] for row in rows] == [user_id]


def test_duplicate_google_subject_is_a_conflict(client):
    subject = f"sub-{uuid4().hex}"
    _run(client.insert_service("account_identities", [{"id": str(uuid4()), "email": "a@example.test", "google_subject": subject}]))

    with pytest.raises(DataServiceError) as info:
        _run(client.insert_service("account_identities", [{"id": str(uuid4()), "email": "b@example.test", "google_subject": subject}]))

    assert info.value.status_code == 409


def test_service_update_returns_changed_rows_and_empty_when_nothing_matches(client):
    user_id = _profile()
    _owner("insert into public.notifications (user_id, text) values (%s, %s)", (user_id, "before"))
    note_id = _owner_rows("select id from public.notifications where user_id = %s", (user_id,))[0][0]

    changed = _run(client.update_service("notifications", {"id": f"eq.{note_id}"}, {"is_read": True}))
    unchanged = _run(client.update_service("notifications", {"id": f"eq.{uuid4()}"}, {"is_read": True}))

    assert changed[0]["is_read"] is True
    assert unchanged == []


def test_service_role_cannot_write_tables_it_has_no_grant_for(client):
    with pytest.raises(DataServiceError) as info:
        _run(client.insert_service("campuses", [{"name": "not allowed", "code": f"x-{uuid4().hex}"}]))

    assert info.value.status_code == 403


def test_update_and_delete_refuse_to_run_without_a_filter(client):
    with pytest.raises(DataServiceError):
        _run(client.update_service("notifications", {}, {"is_read": True}))
    with pytest.raises(DataServiceError):
        _run(client.delete_service("notifications", {"select": "id"}))


# --- user calls and row rules -------------------------------------------------------

def test_user_call_sees_only_their_own_profile_row(client):
    campus = _campus()
    me = _profile(campus_id=campus["id"])
    _profile(campus_id=campus["id"])
    token = issue_session_token(me, SECRET)

    rows = _run(client.select_as_user(token, "profiles", {"select": "id"}))

    assert [row["id"] for row in rows] == [me]


def test_service_call_sees_every_profile_in_the_campus(client):
    campus = _campus()
    _profile(campus_id=campus["id"])
    _profile(campus_id=campus["id"])

    rows = _run(client.select_service("profiles", {"select": "id", "campus_id": f"eq.{campus['id']}"}))

    assert len(rows) == 2


def test_invalid_session_token_is_refused_for_user_calls(client):
    with pytest.raises(DataServiceError) as info:
        _run(client.select_as_user("not-a-token", "profiles", {"select": "id"}))

    assert info.value.status_code == 401


def test_paged_user_read_returns_rows_and_the_visible_total(client):
    campus = _campus()
    me = _profile(campus_id=campus["id"])
    token = issue_session_token(me, SECRET)

    rows, total = _run(client.select_page_as_user(token, "profiles", {"select": "id"}, limit=5, offset=0))

    assert total == 1
    assert [row["id"] for row in rows] == [me]


# --- RPC ----------------------------------------------------------------------------

def test_scalar_rpc_returns_the_json_result_for_the_calling_user(client):
    # staff_dashboard_stats is granted to the authenticated role only, so call it as a user.
    campus = _campus()
    faculty = _profile(role="faculty", campus_id=campus["id"])
    token = issue_session_token(faculty, SECRET)

    result = _run(client.rpc_as_user(token, "staff_dashboard_stats", {}))

    assert isinstance(result, dict)


def test_service_role_cannot_call_a_user_only_rpc(client):
    with pytest.raises(DataServiceError) as info:
        _run(client.rpc_service("staff_dashboard_stats", {}))

    assert info.value.status_code == 403


def test_rpc_with_unsafe_argument_name_is_refused(client):
    with pytest.raises(DataServiceError):
        _run(client.rpc_service("staff_dashboard_stats", {"p-bad": 1}))


# --- files --------------------------------------------------------------------------

def test_file_operations_go_through_the_object_store(client):
    key = f"{uuid4()}/{uuid4()}.pdf"
    data = b"%PDF-1.4 synthetic"

    _run(client.upload_object("documents", key, data, "application/pdf"))

    assert _run(client.download_object("documents", key)) == data
    _run(client.delete_object("documents", key))
    with pytest.raises(DataServiceError) as info:
        _run(client.download_object("documents", key))
    assert info.value.status_code == 404
