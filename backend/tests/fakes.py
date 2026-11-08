"""In-memory test doubles for the Supabase and OpenAI clients.

These model only what the service tests need. Row visibility under RLS is
modelled by the `visible` callable passed in; the real RLS behaviour is verified
against the dev project separately.
"""

import copy
from datetime import datetime, timezone
from collections import defaultdict
from typing import Any, Callable

from app.services.supabase_client import SupabaseError

RESERVED_PARAMS = {"select", "order", "limit", "offset"}
UNIQUE_COLUMNS = {"tickets": ["source_message_id"]}


def _matches(row: dict[str, Any], params: dict[str, str]) -> bool:
    for key, value in params.items():
        if key in RESERVED_PARAMS:
            continue
        if not value.startswith("eq."):
            raise NotImplementedError(f"fake supports only eq filters, got {value}")
        if str(row.get(key)) != value[3:]:
            return False
    return True


class FakeSupabase:
    def __init__(self, visible: Callable[[str, str, dict[str, Any]], bool] | None = None):
        self.tables: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.storage: dict[str, bytes] = {}
        self.rpc_rows: list[dict[str, Any]] = []
        self.rpc_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.user_calls: list[tuple[str, str]] = []
        self._visible = visible or (lambda token, table, row: True)
        self.fail_storage = False

    # service calls
    async def select_service(self, table, params):
        return [copy.deepcopy(r) for r in self.tables[table] if _matches(r, params)]

    async def select_all_service(self, table, params, page_size=1000):
        return await self.select_service(table, {k: v for k, v in params.items() if k not in ("limit", "offset")})

    async def insert_service(self, table, rows):
        for row in rows:
            for column in UNIQUE_COLUMNS.get(table, []):
                if row.get(column) is not None and any(
                    existing.get(column) == row[column] for existing in self.tables[table]
                ):
                    raise SupabaseError(409, f"duplicate key on {table}.{column}")
            stored = copy.deepcopy(row)
            stored.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            if table == "tickets" and "ticket_number" not in stored:
                stored["ticket_number"] = f"UB-{len(self.tables[table]) + 1:04d}"
            self.tables[table].append(stored)

    async def update_service(self, table, filters, values):
        updated = []
        for row in self.tables[table]:
            if _matches(row, filters):
                row.update(values)
                updated.append(copy.deepcopy(row))
        return updated

    async def upload_object(self, bucket, path, content, content_type):
        if self.fail_storage:
            raise SupabaseError(500, "storage down")
        self.storage[f"{bucket}/{path}"] = content

    # user calls (RLS simulated through the visible callable)
    async def select_as_user(self, access_token, table, params):
        self.user_calls.append((access_token, table))
        return [
            copy.deepcopy(r)
            for r in self.tables[table]
            if _matches(r, params) and self._visible(access_token, table, r)
        ]

    async def rpc_as_user(self, access_token, function, payload):
        self.rpc_calls.append((access_token, function, payload))
        return copy.deepcopy(self.rpc_rows)


class FakeAI:
    """Deterministic embeddings and a scripted answer. Records what was sent."""

    def __init__(self, reply: str = "", fail_embed: bool = False):
        self.reply = reply
        self.fail_embed = fail_embed
        self.embedded: list[str] = []
        self.completions: list[tuple[str, str]] = []

    async def embed(self, texts):
        if self.fail_embed:
            from app.ai.openai_client import OpenAIError

            raise OpenAIError("embedding failed")
        self.embedded.extend(texts)
        return [[float(len(t) % 7) / 10 + 0.01] * 1536 for t in texts]

    async def complete(self, system, user):
        self.completions.append((system, user))
        return self.reply
