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
# Columns PostgREST returns even when a row omits them (database defaults or nulls).
ROW_DEFAULTS = {
    "documents": {
        "original_filename": None, "mime_type": None, "file_size_bytes": None, "department_id": None,
        "page_count": None, "last_error": None, "processing_started_at": None,
        "processing_attempts": 0, "replaces_document_id": None,
    },
}


def _matches(row: dict[str, Any], params: dict[str, str]) -> bool:
    for key, value in params.items():
        if key in RESERVED_PARAMS:
            continue
        if value.startswith("eq."):
            if str(row.get(key)) != value[3:]:
                return False
        elif value.startswith("neq."):
            if str(row.get(key)) == value[4:]:
                return False
        elif value == "is.null":
            if row.get(key) is not None:
                return False
        else:
            raise NotImplementedError(f"fake does not support filter {value}")
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
        self.rpc_responses: dict[str, Any] = {}

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
            for column, default in ROW_DEFAULTS.get(table, {}).items():
                stored.setdefault(column, default)
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

    async def download_object(self, bucket, path):
        key = f"{bucket}/{path}"
        if key not in self.storage:
            raise SupabaseError(404, "object not found")
        return self.storage[key]

    async def delete_object(self, bucket, path):
        self.storage.pop(f"{bucket}/{path}", None)

    async def delete_service(self, table, filters):
        self.tables[table] = [r for r in self.tables[table] if not _matches(r, filters)]

    async def insert_service_batched(self, table, rows, batch_size=200):
        await self.insert_service(table, rows)

    async def count_as_user(self, access_token, table, params):
        return len(await self.select_as_user(access_token, table, {k: v for k, v in params.items()}))

    async def select_page_as_user(self, access_token, table, params, limit, offset):
        rows = await self.select_as_user(access_token, table, params)
        order = params.get("order")
        if order and order.startswith("created_at.desc"):
            rows.sort(key=lambda r: str(r.get("created_at")), reverse=True)
        return rows[offset : offset + limit], len(rows)

    async def rpc_service(self, function, payload):
        if function == "claim_document_jobs":
            return self._claim(payload)
        if function == "publish_document_version":
            return self._publish(payload["p_document_id"])
        if function in self.rpc_responses:
            return self.rpc_responses[function]
        raise NotImplementedError(f"fake has no service RPC {function}")

    def _claim(self, payload):
        claimed = []
        for row in self.tables["documents"]:
            if len(claimed) >= payload["p_limit"]:
                break
            if row["processing_status"] == "pending" and row.get("processing_attempts", 0) < payload["p_max_attempts"]:
                row["processing_status"] = "processing"
                row["processing_attempts"] = row.get("processing_attempts", 0) + 1
                claimed.append(copy.deepcopy(row))
        return claimed

    def _publish(self, document_id):
        for row in self.tables["documents"]:
            if row["id"] == document_id:
                if row["publication_status"] != "draft" or row["processing_status"] != "ready":
                    raise SupabaseError(400, '{"message":"document_not_publishable"}')
                row["publication_status"] = "published"
                if row.get("replaces_document_id"):
                    for old in self.tables["documents"]:
                        if old["id"] == row["replaces_document_id"] and old["publication_status"] == "published":
                            old["publication_status"] = "archived"
                return copy.deepcopy(row)
        raise SupabaseError(400, '{"message":"document_not_publishable"}')

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
        if function == "staff_dashboard_stats":
            return copy.deepcopy(self.rpc_responses.get(function, {}))
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
