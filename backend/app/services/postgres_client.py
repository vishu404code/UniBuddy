"""Data client on direct Postgres. It has the same methods and filter syntax as SupabaseClient,
so services don't change when the backend is switched.

- Service calls run as the service_role (bypasses row rules). Callers must authorize first.
- User calls take the caller's UniBuddy session token. The user is read from the token,
  and the transaction runs as the authenticated role with app.user_id set, so row rules apply.
- Every identifier is checked against a strict pattern. Every value is a query parameter.
- Filters use PostgREST-style strings, such as "eq.<value>", "in.(a,b)" and "is.null".
"""

import asyncio
import re
from collections.abc import Callable
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.services.errors import DataServiceError
from app.storage.objects import ObjectNotFound, ObjectStore, ObjectStoreError

IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
RESERVED = frozenset({"select", "order", "limit", "offset"})
COMPARISONS = {"eq": "=", "neq": "<>", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
TABLE_FUNCTIONS = frozenset({"match_document_chunks", "claim_document_jobs", "publish_document_version"})
SINGLE_ROW_FUNCTIONS = frozenset({"publish_document_version"})


def _ident(name: str) -> str:
    if not isinstance(name, str) or not IDENT.match(name):
        raise DataServiceError(400, "invalid identifier")
    return f'"{name}"'


def _where(filters: dict[str, str]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for column, expression in filters.items():
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
    ):
        if not dsn:
            raise DataServiceError(503, "database is not configured")
        self._dsn = dsn
        self._session_secret = session_secret
        self._objects = object_store
        self._connect = connect or (lambda url: psycopg.connect(url, row_factory=dict_row))

    # --- helpers --------------------------------------------------------------------

    def _user_id(self, access_token: str) -> UUID:
        from app.auth.session import SessionError, read_session_token

        try:
            return read_session_token(access_token, self._session_secret)
        except SessionError as exc:
            raise DataServiceError(401, "invalid session") from exc

    def _run_sync(self, as_user: UUID | None, work: Callable[[psycopg.Connection], Any]) -> Any:
        try:
            with self._connect(self._dsn) as conn:
                if as_user is None:
                    conn.execute("set local role service_role")
                else:
                    conn.execute("set local role authenticated")
                    conn.execute("select set_config('app.user_id', %s, true)", (str(as_user),))
                result = work(conn)
                conn.commit()
                return result
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
        sql, values = self._select_sql(table, {**params, "limit": str(limit), "offset": str(offset)})
        count_sql, count_values = self._select_sql(table, {k: v for k, v in params.items() if k not in ("select", "order")})

        def work(conn):
            rows = conn.execute(sql, values).fetchall()
            total = conn.execute(f"select count(*) as n from ({count_sql}) as counted", count_values).fetchone()["n"]
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
            raise DataServiceError(503, "file storage is not configured")
        return self._objects

    async def upload_object(self, bucket: str, path: str, content: bytes, content_type: str) -> None:
        try:
            await self._store().put_pdf(path, content)
        except ObjectStoreError as exc:
            raise DataServiceError(503, "file storage request failed") from exc

    async def download_object(self, bucket: str, path: str) -> bytes:
        try:
            return await self._store().get_pdf(path)
        except ObjectNotFound as exc:
            raise DataServiceError(404, "file not found") from exc
        except ObjectStoreError as exc:
            raise DataServiceError(503, "file storage request failed") from exc

    async def delete_object(self, bucket: str, path: str) -> None:
        try:
            await self._store().delete(path)
        except ObjectStoreError as exc:
            raise DataServiceError(503, "file storage request failed") from exc
