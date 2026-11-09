"""Stage 1 row-level rules, run as a non-owner role on the local database.

Each test runs in one transaction that is rolled back, so nothing persists. The
policies here are a small example of the rules that will replace the Supabase
policies. They show the mechanism: campus scoping, published-only reads, and no
access without a signed-in user.
"""

import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.db.postgres import connect, execute, fetch_all, fetch_one, set_session_user

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL is not set")

HELPERS = (Path(__file__).resolve().parents[1] / "app" / "db" / "sql" / "access_helpers.sql").read_text()
APP_ROLE = "unibuddy_stage1_app"

CAMPUS_A = uuid4()
CAMPUS_B = uuid4()
DEPT_A = uuid4()
STUDENT_A = uuid4()
FACULTY_B = uuid4()
STUDENT_NONE = uuid4()  # a signed-in user with no profile
DOC_A_PUBLISHED = uuid4()
DOC_A_DRAFT = uuid4()
DOC_B_PUBLISHED = uuid4()


@pytest.fixture
def conn():
    connection = connect(DSN)
    try:
        execute(connection, "create table public.profiles (id uuid primary key, role text not null, campus_id uuid, department_id uuid)")
        execute(connection, HELPERS)  # SQL functions check their tables when created, so profiles must exist first
        execute(connection, "create table public.documents (id uuid primary key, campus_id uuid not null, title text not null, publication_status text not null)")
        execute(
            connection,
            "insert into public.profiles (id, role, campus_id, department_id) values (%s, 'student', %s, %s), (%s, 'faculty', %s, null)",
            (STUDENT_A, CAMPUS_A, DEPT_A, FACULTY_B, CAMPUS_B),
        )
        execute(
            connection,
            "insert into public.documents (id, campus_id, title, publication_status) values (%s, %s, 'A published', 'published'), (%s, %s, 'A draft', 'draft'), (%s, %s, 'B published', 'published')",
            (DOC_A_PUBLISHED, CAMPUS_A, DOC_A_DRAFT, CAMPUS_A, DOC_B_PUBLISHED, CAMPUS_B),
        )
        execute(connection, "alter table public.documents enable row level security")
        execute(connection, "alter table public.documents force row level security")
        execute(
            connection,
            "create policy documents_read on public.documents for select "
            "using (campus_id = unibuddy_auth.campus_id() and publication_status = 'published')",
        )
        execute(connection, f"create role {APP_ROLE} nologin")
        execute(connection, f"grant usage on schema public, unibuddy_auth to {APP_ROLE}")
        execute(connection, f"grant select on public.documents, public.profiles to {APP_ROLE}")
        execute(connection, f"grant execute on all functions in schema unibuddy_auth to {APP_ROLE}")
        yield connection
    finally:
        connection.rollback()
        connection.close()


def _as_app_user(conn):
    execute(conn, f"set local role {APP_ROLE}")


def _visible_titles(conn):
    return sorted(row["title"] for row in fetch_all(conn, "select title from public.documents"))


def test_student_sees_only_published_documents_of_their_own_campus(conn):
    set_session_user(conn, STUDENT_A)
    _as_app_user(conn)

    assert _visible_titles(conn) == ["A published"]


def test_faculty_of_another_campus_cannot_read_campus_a_by_id(conn):
    set_session_user(conn, FACULTY_B)
    _as_app_user(conn)

    row = fetch_one(conn, "select id from public.documents where id = %s", (DOC_A_PUBLISHED,))

    assert row is None
    assert _visible_titles(conn) == ["B published"]


def test_draft_documents_are_hidden_even_from_their_own_campus(conn):
    set_session_user(conn, STUDENT_A)
    _as_app_user(conn)

    assert "A draft" not in _visible_titles(conn)


def test_no_signed_in_user_sees_nothing(conn):
    _as_app_user(conn)

    assert _visible_titles(conn) == []


def test_signed_in_user_without_a_profile_sees_nothing(conn):
    set_session_user(conn, STUDENT_NONE)
    _as_app_user(conn)

    assert _visible_titles(conn) == []


def test_helpers_report_the_profile_of_the_current_user(conn):
    set_session_user(conn, STUDENT_A)

    row = fetch_one(
        conn,
        "select unibuddy_auth.app_role() as role, unibuddy_auth.campus_id() as campus, "
        "unibuddy_auth.department_id() as dept",
    )

    assert row["role"] == "student"
    assert row["campus"] == CAMPUS_A
    assert row["dept"] == DEPT_A


def test_a_superuser_connection_bypasses_row_rules_so_the_backend_must_not_use_one(conn):
    # Finding: superusers ignore row policies, even with FORCE ROW LEVEL SECURITY. The
    # backend must connect as a non-superuser role. This test documents that rule.
    set_session_user(conn, STUDENT_A)

    owner = fetch_one(conn, "select rolsuper from pg_roles where rolname = current_user")
    assert owner["rolsuper"] is True
    assert "A draft" in _visible_titles(conn)


def test_the_app_role_is_not_a_superuser(conn):
    _as_app_user(conn)

    role = fetch_one(conn, "select rolsuper from pg_roles where rolname = current_user")

    assert role["rolsuper"] is False


def test_switching_user_inside_a_transaction_changes_what_is_visible(conn):
    set_session_user(conn, STUDENT_A)
    _as_app_user(conn)
    assert _visible_titles(conn) == ["A published"]

    set_session_user(conn, FACULTY_B)

    assert _visible_titles(conn) == ["B published"]
