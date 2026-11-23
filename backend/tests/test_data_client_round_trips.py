"""The data client's transaction shape: fewer round trips, same isolation.

Each call runs as one explicit transaction in pipeline mode. These tests check, on a local database, that the
role and app.user_id stay inside that transaction, that a failed call leaves nothing behind, and that the pool
pings a connection only when it has been idle. Without TEST_DATABASE_URL the database tests are skipped.
"""

import asyncio
import os
from uuid import uuid4

import psycopg
import pytest

from app.services import postgres_client as pc
from app.services import request_timing
from app.services.errors import DataServiceError
from app.services.postgres_client import PostgresClient

DSN = os.environ.get("TEST_DATABASE_URL")
SECRET = "s" * 40
needs_db = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL is not set")


def _settings(conn):
    return conn.execute(
        "select current_user as role, coalesce(current_setting('app.user_id', true), '') as user_id"
    ).fetchone()


@needs_db
def test_role_and_user_are_local_to_one_call_on_a_reused_connection():
    client = PostgresClient(DSN, SECRET, pool_size=1)  # one connection: every call reuses it
    user = uuid4()
    try:
        as_user = client._run_sync(user, _settings)
        as_service = client._run_sync(None, _settings)
        with client._pool.connection() as conn:  # the same connection, outside any client call
            bare = _settings(conn)
            status = conn.info.transaction_status
    finally:
        client._pool.close()

    assert as_user == {"role": "authenticated", "user_id": str(user)}
    assert as_service == {"role": "service_role", "user_id": ""}
    assert bare["role"] not in ("authenticated", "service_role")
    assert bare["user_id"] == ""
    assert status == psycopg.pq.TransactionStatus.IDLE


@needs_db
def test_a_failed_call_rolls_back_and_the_connection_stays_usable():
    client = PostgresClient(DSN, SECRET, pool_size=1)
    code = f"rt-{uuid4().hex[:10]}"

    def insert_then_fail(conn):
        conn.execute("insert into public.campuses (name, code) values (%s, %s)", (f"Campus {code}", code))
        conn.execute("select 1 / 0").fetchall()

    try:
        with pytest.raises(DataServiceError) as caught:
            # Owner-level work on purpose: the point is the rollback, not the grant.
            client._run_sync(None, lambda conn: (conn.execute("reset role"), insert_then_fail(conn)))
        after = client._run_sync(None, lambda conn: conn.execute("select 2 as v").fetchone())
    finally:
        client._pool.close()
    with psycopg.connect(DSN) as owner:
        left = owner.execute("select count(*) from public.campuses where code = %s", (code,)).fetchone()[0]

    assert caught.value.status_code == 400  # division by zero is a data error
    assert left == 0
    assert after == {"v": 2}


@needs_db
def test_database_time_is_added_to_the_current_request():
    client = PostgresClient(DSN, SECRET, pool_size=1)
    timing, token = request_timing.start()
    try:
        asyncio.run(client.select_service("campuses", {"select": "id", "limit": "1"}))
        asyncio.run(client.select_service("campuses", {"select": "id", "limit": "1"}))
    finally:
        request_timing.finish(token)
        client._pool.close()

    assert timing.db_calls == 2
    assert timing.parts_ms["db"] > 0
    assert "db;dur=" in timing.server_timing(timing.total_ms())


def test_only_an_idle_connection_is_pinged(monkeypatch):
    client = PostgresClient.__new__(PostgresClient)  # no pool or database: only the check logic
    client._last_used = pc.weakref.WeakKeyDictionary()
    pings = []
    monkeypatch.setattr(pc.ConnectionPool, "check_connection", staticmethod(lambda conn: pings.append(conn)))

    class Conn:
        pass

    conn = Conn()
    now = [1000.0]
    monkeypatch.setattr(pc.time, "monotonic", lambda: now[0])

    client._check_if_idle(conn)  # never used: pinged
    client._mark_used(conn)
    now[0] += 5
    client._check_if_idle(conn)  # used 5 s ago: handed out directly
    now[0] += pc.IDLE_CHECK_SECONDS + 1
    client._check_if_idle(conn)  # idle too long: pinged

    assert pings == [conn, conn]


def test_timing_outside_a_request_is_ignored():
    request_timing.record("db", 12.0, db_call=True)  # no request open: must not raise


@needs_db
def test_paged_user_read_total_is_the_full_count_also_past_the_end():
    from app.auth.session import issue_session_token

    client = PostgresClient(DSN, SECRET, pool_size=1)
    campus = uuid4()
    users = [uuid4() for _ in range(3)]
    code = f"pg-{campus.hex[:10]}"
    try:
        with psycopg.connect(DSN) as owner:
            owner.execute("insert into public.campuses (id, name, code) values (%s, %s, %s)", (campus, code, code))
            for user in users:
                email = f"{user.hex}@example.test"
                owner.execute("insert into public.account_identities (id, email) values (%s, %s)", (user, email))
                owner.execute(
                    "insert into public.profiles (id, email, role, campus_id) values (%s, %s, 'student', %s)",
                    (user, email, campus),
                )
            owner.commit()
        token = issue_session_token(users[0], SECRET)
        params = {"select": "id", "campus_id": f"eq.{campus}"}
        # Row-level security decides what a student can see; the total must match that visible set.
        visible = asyncio.run(client.select_as_user(token, "profiles", params))
        first_page, total = asyncio.run(client.select_page_as_user(token, "profiles", params, 2, 0))
        past_end, total_past = asyncio.run(client.select_page_as_user(token, "profiles", params, 2, 10))
    finally:
        client._pool.close()
        with psycopg.connect(DSN) as owner:
            owner.execute("delete from public.profiles where id = any(%s)", (users,))
            owner.execute("delete from public.account_identities where id = any(%s)", (users,))
            owner.execute("delete from public.campuses where id = %s", (campus,))
            owner.commit()

    assert len(visible) == total == total_past
    assert past_end == []
    assert [row["id"] for row in first_page] == [row["id"] for row in visible][:2]
    assert all(set(row) == {"id"} for row in first_page)  # the internal total column is removed from rows
