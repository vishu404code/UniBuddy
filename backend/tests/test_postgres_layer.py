"""Tests for the direct Postgres layer. They run only when TEST_DATABASE_URL is set,
for example to the local PostgreSQL 17 test server. They use temporary tables only,
so nothing persists in that database.
"""

import os
from uuid import uuid4

import pytest

from app.db.postgres import EMBEDDING_DIMENSIONS, connect, execute, fetch_all, fetch_one, set_session_user, vector_literal

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL is not set")


@pytest.fixture
def conn():
    connection = connect(DSN)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def test_pgvector_extension_is_installed(conn):
    row = fetch_one(conn, "select extversion from pg_extension where extname = %s", ("vector",))

    assert row is not None


def test_user_setting_is_visible_in_the_transaction_only(conn):
    user_id = uuid4()
    set_session_user(conn, user_id)

    inside = fetch_one(conn, "select current_setting('app.user_id', true) as value")
    conn.commit()
    after = fetch_one(conn, "select current_setting('app.user_id', true) as value")

    assert inside["value"] == str(user_id)
    assert after["value"] in (None, "")


def test_parameters_are_sent_as_values_not_sql_text(conn):
    tricky = "x'); drop table if exists nothing; --"

    row = fetch_one(conn, "select %s::text as value", (tricky,))

    assert row["value"] == tricky


def test_vector_round_trip_and_cosine_ordering(conn):
    execute(conn, "create temp table probe_chunks (id int, embedding vector(1536))")
    near = [0.1] * EMBEDDING_DIMENSIONS
    far = [-0.1] * EMBEDDING_DIMENSIONS
    execute(
        conn,
        "insert into probe_chunks (id, embedding) values (%s, %s::vector), (%s, %s::vector)",
        (1, vector_literal(far), 2, vector_literal(near)),
    )

    rows = fetch_all(
        conn,
        "select id, 1 - (embedding <=> %s::vector) as similarity from probe_chunks order by embedding <=> %s::vector",
        (vector_literal(near), vector_literal(near)),
    )

    assert [row["id"] for row in rows] == [2, 1]
    assert rows[0]["similarity"] > 0.99


def test_execute_reports_rows_changed(conn):
    execute(conn, "create temp table probe_counts (id int)")
    execute(conn, "insert into probe_counts values (1), (2), (3)")

    changed = execute(conn, "update probe_counts set id = id + 10 where id > %s", (1,))

    assert changed == 2


def test_vector_literal_rejects_wrong_dimensions_and_non_numbers_are_formatted():
    with pytest.raises(ValueError):
        vector_literal([0.1, 0.2])
    literal = vector_literal([1] * EMBEDDING_DIMENSIONS)
    assert literal.startswith("[1.0,1.0") and literal.endswith("]")
