"""Data client on direct Postgres. It has the same methods and filter syntax as PostgresClient,
so services don't change when the backend is switched.

- Service calls run as the service_role (bypasses row rules). Callers must authorize first.
- User calls take the caller's UniBuddy session token. The user is read from the token,
  and the transaction runs as the authenticated role with app.user_id set, so row rules apply.
- Every identifier is checked against a strict pattern. Every value is a query parameter.
- Filters use PostgREST-style strings, such as "eq.<value>", "in.(a,b)" and "is.null".
"""

import asyncio
import logging
import re
import time
import weakref
from collections.abc import Callable
from typing import Any
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool, PoolTimeout

from app.services import request_timing
from app.services.errors import DataServiceError
from app.storage.objects import ObjectNotFound, ObjectStore, ObjectStoreError

IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
logger = logging.getLogger("unibuddy.data")
RESERVED = frozenset({"select", "order", "limit", "offset"})
COMPARISONS = {"eq": "=", "neq": "<>", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
TABLE_FUNCTIONS = frozenset({"match_document_chunks", "claim_document_jobs", "publish_document_version"})
SINGLE_ROW_FUNCTIONS = frozenset({"publish_document_version"})
# A pooled connection that has been idle longer than this is pinged before use. One used more recently is
# handed out directly: the ping is a full round trip to Neon, and most requests reuse a connection within seconds.
IDLE_CHECK_SECONDS = 30.0
PAGE_TOTAL = "ub_page_total"


def _ident(name: str) -> str:
    if not isinstance(name, str) or not IDENT.match(name):
        raise DataServiceError(400, "invalid identifier")
    return f'"{name}"'


def _where(filters: dict[str, str]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for key, expression in filters.items():
        # A key may carry a suffix after "~" so one column can have two conditions (a date range).
        column = key.partition("~")[0]
        if column in RESERVED:
            continue
        col = _ident(column)
        op, _, raw = str(expression).partition(".")
        if op in COMPARISONS:
            clauses.append(f"{col} {COMPARISONS[op]} %s")
            params.append(raw)
        elif op == "is" and raw == "null":
            clauses.append(f"{col} is null")
        elif op == "is" and raw in ("true", "false"):
            clauses.append(f"{col} is {raw}")
        elif op == "in" and raw.startswith("(") and raw.endswith(")"):
            clauses.append(f"{col}::text = any(%s)")
            params.append([item for item in raw[1:-1].split(",") if item != ""])
        else:
            raise DataServiceError(400, "unsupported filter")
    return (" and ".join(clauses) or "true"), params


def _order(expression: str | None) -> str:
    if not expression:
        return ""
    parts = []
    for item in expression.split(","):
        column, _, direction = item.strip().partition(".")
        direction = direction or "asc"
        if direction not in ("asc", "desc"):
            raise DataServiceError(400, "unsupported order")
        parts.append(f"{_ident(column)} {direction}")
    return " order by " + ", ".join(parts)


def _columns(expression: str | None) -> str:
    if not expression or expression == "*":
        return "*"
    return ", ".join(_ident(column) for column in expression.split(","))


def _int(value: str | None, default: int | None) -> int | None:
    if value is None:
        return default
    if not str(value).isdigit():
        raise DataServiceError(400, "limit and offset must be whole numbers")
    return int(value)


def _adapt(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return Json(value)
    return value


def _rpc_value(value: Any) -> Any:
    # Scalars are sent as text so Postgres picks the function's own argument type.
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return Json(value)


class PostgresClient:
    def __init__(
        self,
        dsn: str,
        session_secret: str,
        object_store: ObjectStore | None = None,
        connect: Callable[[str], psycopg.Connection] | None = None,
        pool_size: int = 5,
    ):
        if not dsn:
            raise DataServiceError(503, "database is not configured")
        self._dsn = dsn
        self._session_secret = session_secret
        self._objects = object_store
        # Production: a small pool, so each request reuses an open connection instead of paying for
        # a new TLS handshake to Neon. Tests that inject `connect` keep their own connection behaviour.
        self._pool: ConnectionPool | None = None
        self._last_used: weakref.WeakKeyDictionary[psycopg.Connection, float] = weakref.WeakKeyDictionary()
        if connect is None:
            self._pool = ConnectionPool(
                conninfo=dsn,
                min_size=1,
                max_size=pool_size,
                # Autocommit: each call opens its own transaction explicitly (see _run_sync), so the opening
                # statements and the query travel together instead of one round trip each.
                kwargs={"row_factory": dict_row, "connect_timeout": 10, "autocommit": True},
                check=self._check_if_idle,
                reset=self._mark_used,
                timeout=15,
                open=True,
            )
        self._connect = connect or (lambda url: psycopg.connect(url, row_factory=dict_row))

    def _mark_used(self, conn: psycopg.Connection) -> None:
        self._last_used[conn] = time.monotonic()

    def _check_if_idle(self, conn: psycopg.Connection) -> None:
        last = self._last_used.get(conn)
        if last is None or time.monotonic() - last > IDLE_CHECK_SECONDS:
            ConnectionPool.check_connection(conn)

    def _checkout(self):
        """Context manager that yields one connection; the pool commits or rolls back on exit."""
        if self._pool is not None:
            return self._pool.connection()
        return self._connect(self._dsn)

    # --- helpers --------------------------------------------------------------------

    def _user_id(self, access_token: str) -> UUID:
        from app.auth.session import SessionError, read_session_token

        try:
            return read_session_token(access_token, self._session_secret)
        except SessionError as exc:
            raise DataServiceError(401, "invalid session") from exc

    @staticmethod
    def _in_transaction(conn: psycopg.Connection, as_user: UUID | None, work: Callable[[psycopg.Connection], Any]) -> Any:
        """One transaction: the role and user settings, the work, then commit.

        Pipeline mode sends begin, the settings and the first query together, so a read costs about two round
        trips (query, commit) instead of five. Both settings are transaction-local (is_local => true), exactly
        like SET LOCAL ROLE, so nothing leaks to the next request on the same connection.
        """
        if not conn.autocommit:
            conn.autocommit = True  # injected connections (tests): the transaction is opened explicitly below
        try:
            with conn.pipeline():
                conn.execute("begin")
                if as_user is None:
                    conn.execute("select set_config('role', 'service_role', true)")
                else:
                    conn.execute(
                        "select set_config('role', 'authenticated', true), set_config('app.user_id', %s, true)",
                        (str(as_user),),
                    )
                result = work(conn)
                conn.execute("commit")
            return result
        except BaseException:
            if not conn.closed and conn.info.transaction_status != TransactionStatus.IDLE:
                try:
                    conn.rollback()
                except psycopg.Error:
                    pass  # the pool discards a broken connection
            raise

    def _run_sync(self, as_user: UUID | None, work: Callable[[psycopg.Connection], Any]) -> Any:
        started = time.perf_counter()
        try:
            with self._checkout() as conn:
                return self._in_transaction(conn, as_user, work)
        except DataServiceError:
            raise
        except psycopg.errors.UniqueViolation as exc:
            raise DataServiceError(409, str(exc).splitlines()[0]) from exc
        except psycopg.errors.InsufficientPrivilege as exc:
            raise DataServiceError(403, "not allowed") from exc
        except psycopg.errors.RaiseException as exc:
            raise DataServiceError(400, str(exc).splitlines()[0]) from exc
        except psycopg.errors.DataError as exc:
            raise DataServiceError(400, str(exc).splitlines()[0]) from exc
        except psycopg.OperationalError as exc:
            raise DataServiceError(503, "database unavailable") from exc
        except psycopg.Error as exc:
            raise DataServiceError(500, "database request failed") from exc
        finally:
            request_timing.record("db", (time.perf_counter() - started) * 1000, db_call=True)

    async def _run(self, as_user: UUID | None, work: Callable[[psycopg.Connection], Any]) -> Any:
        return await asyncio.to_thread(self._run_sync, as_user, work)

    # --- SELECT ---------------------------------------------------------------------

    @staticmethod
    def _select_sql(table: str, params: dict[str, str]) -> tuple[str, list[Any]]:
        where, values = _where(params)
        sql = (
            f"select {_columns(params.get('select'))} from {_ident(table)} where {where}"
            f"{_order(params.get('order'))}"
        )
        limit = _int(params.get("limit"), None)
        offset = _int(params.get("offset"), None)
        if limit is not None:
            sql += f" limit {limit}"
        if offset is not None:
            sql += f" offset {offset}"
        return sql, values

    async def select_service(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        sql, values = self._select_sql(table, params)
        return await self._run(None, lambda c: c.execute(sql, values).fetchall())

    async def select_all_service(self, table: str, params: dict[str, str], page_size: int = 1000) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self.select_service(table, {**params, "limit": str(page_size), "offset": str(offset)})
            rows.extend(page)
            if len(page) < page_size:
                return rows
            offset += page_size

    async def select_as_user(self, access_token: str, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        user = self._user_id(access_token)
        sql, values = self._select_sql(table, params)
        return await self._run(user, lambda c: c.execute(sql, values).fetchall())

    async def select_page_as_user(
        self, access_token: str, table: str, params: dict[str, str], limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        user = self._user_id(access_token)
        # The total comes from a window count in the same query (counted over every matching row, before the
        # limit), so a list page is one query instead of two. A page past the end has no row to carry the
        # total; only then is it counted separately.
        sql, values = self._select_sql(table, {**params, "limit": str(limit), "offset": str(offset)})
        columns = _columns(params.get("select"))
        prefix = f"select {columns} from "
        if not sql.startswith(prefix):
            raise DataServiceError(500, "unexpected page query")
        sql = f"select {columns}, count(*) over () as {PAGE_TOTAL} from " + sql[len(prefix):]
        count_sql, count_values = self._select_sql(table, {k: v for k, v in params.items() if k not in ("select", "order")})

        def work(conn):
            rows = conn.execute(sql, values).fetchall()
            if rows:
                total = rows[0][PAGE_TOTAL]
                for row in rows:
                    del row[PAGE_TOTAL]
            elif offset:
                total = conn.execute(f"select count(*) as n from ({count_sql}) as counted", count_values).fetchone()["n"]
            else:
                total = 0
            return rows, total

        return await self._run(user, work)

    async def count_as_user(self, access_token: str, table: str, params: dict[str, str]) -> int:
        user = self._user_id(access_token)
        sql, values = self._select_sql(table, {k: v for k, v in params.items() if k not in ("select", "order")})
        return await self._run(user, lambda c: c.execute(f"select count(*) as n from ({sql}) as counted", values).fetchone()["n"])

    # --- INSERT / UPDATE / DELETE (service) -----------------------------------------

    async def insert_service(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        columns = list(rows[0].keys())
        if any(list(row.keys()) != columns for row in rows):
            raise DataServiceError(400, "all rows must have the same columns")
        column_sql = ", ".join(_ident(c) for c in columns)
        placeholders = ", ".join("(" + ", ".join("%s" for _ in columns) + ")" for _ in rows)
        values = [_adapt(row[c]) for row in rows for c in columns]
        sql = f"insert into {_ident(table)} ({column_sql}) values {placeholders}"
        await self._run(None, lambda c: c.execute(sql, values))

    async def insert_service_batched(self, table: str, rows: list[dict[str, Any]], batch_size: int = 200) -> None:
        for start in range(0, len(rows), batch_size):
            await self.insert_service(table, rows[start : start + batch_size])

    async def update_service(self, table: str, filters: dict[str, str], values: dict[str, Any]) -> list[dict[str, Any]]:
        where, where_values = _where(filters)
        if not filters or not values:
            raise DataServiceError(400, "update needs filters and values")
        assignments = ", ".join(f"{_ident(c)} = %s" for c in values)
        sql = f"update {_ident(table)} set {assignments} where {where} returning *"
        params = [_adapt(v) for v in values.values()] + where_values
        return await self._run(None, lambda c: c.execute(sql, params).fetchall())

    async def delete_service(self, table: str, filters: dict[str, str]) -> None:
        if not any(column not in RESERVED for column in filters):
            raise DataServiceError(400, "delete needs a filter")
        where, values = _where(filters)
        sql = f"delete from {_ident(table)} where {where}"
        await self._run(None, lambda c: c.execute(sql, values))

    # --- RPC ------------------------------------------------------------------------

    @staticmethod
    def _rpc_sql(function: str, payload: dict[str, Any]) -> tuple[str, list[Any]]:
        name = _ident(function)
        keys = list(payload.keys())
        for key in keys:
            if not IDENT.match(key):
                raise DataServiceError(400, "invalid argument name")
        args = ", ".join(f"{key} => %s" for key in keys)
        values = [_rpc_value(payload[k]) for k in keys]
        if function in TABLE_FUNCTIONS:
            return f"select * from {name}({args})", values
        return f"select {name}({args}) as result", values

    async def rpc_service(self, function: str, payload: dict[str, Any]) -> Any:
        return await self._rpc(None, function, payload)

    async def rpc_as_user(self, access_token: str, function: str, payload: dict[str, Any]) -> Any:
        return await self._rpc(self._user_id(access_token), function, payload)

    async def _rpc(self, as_user: UUID | None, function: str, payload: dict[str, Any]) -> Any:
        sql, values = self._rpc_sql(function, payload)

        def work(conn):
            rows = conn.execute(sql, values).fetchall()
            if function in SINGLE_ROW_FUNCTIONS:
                return rows[0] if rows else None
            if function in TABLE_FUNCTIONS:
                return rows
            return rows[0]["result"] if rows else None

        return await self._run(as_user, work)

    # --- Files (through the object store) -------------------------------------------

    def _store(self) -> ObjectStore:
        if self._objects is None:
            logger.warning("file storage is not configured in this process")
            raise DataServiceError(503, "file storage is not configured")
        return self._objects

    async def upload_object(self, bucket: str, path: str, content: bytes, content_type: str) -> None:
        try:
            await self._store().put_pdf(path, content)
        except ObjectStoreError as exc:
            logger.warning("file storage call failed: %s", type(exc.__cause__).__name__ if exc.__cause__ else "no cause")
            raise DataServiceError(503, "file storage request failed") from exc

    async def download_object(self, bucket: str, path: str) -> bytes:
        try:
            return await self._store().get_pdf(path)
        except ObjectNotFound as exc:
            raise DataServiceError(404, "file not found") from exc
        except ObjectStoreError as exc:
            logger.warning("file storage call failed: %s", type(exc.__cause__).__name__ if exc.__cause__ else "no cause")
            raise DataServiceError(503, "file storage request failed") from exc

    async def delete_object(self, bucket: str, path: str) -> None:
        try:
            await self._store().delete(path)
        except ObjectStoreError as exc:
            logger.warning("file storage call failed: %s", type(exc.__cause__).__name__ if exc.__cause__ else "no cause")
            raise DataServiceError(503, "file storage request failed") from exc
