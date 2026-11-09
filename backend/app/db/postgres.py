"""Direct Postgres access for the replacement data layer.

Every query takes its values as parameters, never as text joined into SQL. The
signed-in user is passed to the database with set_config(..., is_local => true), so
the setting lasts only for the current transaction. Row-level-security policies can
read it with current_setting('app.user_id'), with no risk of leaking it to a later
request on the same connection.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

EMBEDDING_DIMENSIONS = 1536


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row)


def set_session_user(conn: psycopg.Connection, user_id: UUID) -> None:
    """Sets app.user_id for the current transaction only."""
    conn.execute("select set_config('app.user_id', %s, true)", (str(user_id),))


def fetch_all(conn: psycopg.Connection, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    return conn.execute(sql, params).fetchall()


def fetch_one(conn: psycopg.Connection, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
    return conn.execute(sql, params).fetchone()


def execute(conn: psycopg.Connection, sql: str, params: Sequence[Any] = ()) -> int:
    return conn.execute(sql, params).rowcount


def vector_literal(vector: Sequence[float]) -> str:
    """Formats an embedding for a ::vector cast. Only numbers reach the SQL text."""
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise ValueError(f"embedding must have {EMBEDDING_DIMENSIONS} dimensions")
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"
