"""In-memory test doubles for the data and Gemini clients.

These model only what the service tests need. Row visibility under RLS is
modelled by the `visible` callable passed in; the real RLS behaviour is verified
against the dev project separately.
"""

import copy
from uuid import uuid4
from datetime import datetime, timezone
from collections import defaultdict
from typing import Any, Callable

from app.services.errors import DataServiceError

RESERVED_PARAMS = {"select", "order", "limit", "offset"}
UNIQUE_COLUMNS = {"tickets": ["source_message_id"], "registration_requests": ["email"]}
# Columns PostgREST returns even when a row omits them (database defaults or nulls).
ROW_DEFAULTS = {
    "registration_requests": {"status": "pending", "decided_at": None, "decided_by": None, "decision_reason": None},
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


class FakeDataClient:
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
                    raise DataServiceError(409, f"duplicate key on {table}.{column}")
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
            raise DataServiceError(500, "storage down")
        self.storage[f"{bucket}/{path}"] = content

    async def download_object(self, bucket, path):
        key = f"{bucket}/{path}"
        if key not in self.storage:
            raise DataServiceError(404, "object not found")
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
        if function == "open_student_signup":
            account, email = payload["p_account"], payload["p_email"].lower()
            if any(row["id"] == account or row["email"] == email for row in self.tables["profiles"]):
                raise DataServiceError(400, "profile_exists")
            self.tables["profiles"].append({
                "id": account, "email": email, "full_name": payload.get("p_full_name"), "role": "student",
                "campus_id": None, "department_id": None, "cross_campus_record_access": False,
            })
            return {"id": account, "role": "student"}
        if function == "claim_document_jobs":
            return self._claim(payload)
        if function == "publish_document_version":
            return self._publish(payload["p_document_id"])
        if function == "provisioning_precheck":
            return self._provisioning_precheck(payload)
        if function == "super_admin_provision_precheck":
            return self._super_admin_precheck(payload)
        if function == "super_admin_provision_complete":
            return self._super_admin_complete(payload)
        if function == "provisioning_complete":
            return self._provisioning_complete(payload)
        if function == "provisioning_record_failure":
            self._audit(payload["p_actor"], payload["p_email"], payload["p_role"], payload["p_outcome"],
                        payload["p_reason"], payload.get("p_user_id"))
            return None
        if function in self.rpc_responses:
            return self.rpc_responses[function]
        raise NotImplementedError(f"fake has no service RPC {function}")

    # Emulates the SQL provisioning functions in app/db/migrations/20261108120900. The SQL
    # itself is validated against PostgreSQL in tests/sql/provisioning_test.sql.
    def _audit(self, actor_id, email, role, outcome, reason, user_id=None):
        self.tables["provisioning_audit"].append({
            "actor_id": actor_id, "target_email": email.lower(), "target_role": role,
            "outcome": outcome, "reason": reason, "target_user_id": user_id,
        })

    def _actor(self, actor_id):
        return next((r for r in self.tables["profiles"] if r["id"] == actor_id), None)

    def _provisioning_precheck(self, p):
        actor = self._actor(p["p_actor"])
        role, dept, email = p["p_role"], p["p_department"], p["p_email"].lower()
        reason = None
        if actor is None or actor["role"] != "authority":
            reason = "not_authority"
        elif not actor.get("campus_id"):
            reason = "no_campus"
        elif role not in ("student", "faculty"):
            reason = "invalid_role"
        elif role == "faculty" and not dept:
            reason = "department_required"
        elif dept and not any(d["id"] == dept and d["campus_id"] == actor["campus_id"] for d in self.tables["departments"]):
            reason = "department_not_in_campus"
        elif any(r["email"] == email for r in self.tables["profiles"]):
            reason = "email_exists"
        if reason:
            self._audit(p["p_actor"], email, role, "rejected", reason)
            return {"ok": False, "reason": reason}
        return {"ok": True, "campus_id": actor["campus_id"]}

    def _super_admin_precheck(self, p):
        actor = self._actor(p["p_actor"])
        role, campus, email = p["p_role"], p.get("p_campus"), p["p_email"].lower()
        reason = None
        if actor is None or actor["role"] != "super_admin":
            reason = "not_super_admin"
        elif role not in ("authority", "management"):
            reason = "invalid_role"
        elif role == "authority" and not campus:
            reason = "campus_required"
        elif campus and not any(c["id"] == campus for c in self.tables["campuses"]):
            reason = "campus_not_found"
        elif any(r["email"] == email for r in self.tables["profiles"]):
            reason = "email_exists"
        if reason:
            self._audit(p["p_actor"], email, role, "rejected", reason)
            return {"ok": False, "reason": reason}
        return {"ok": True}

    def _super_admin_complete(self, p):
        actor = self._actor(p["p_actor"])
        if actor is None or actor["role"] != "super_admin":
            raise DataServiceError(400, "provisioning_not_permitted")
        profile = {
            "id": p["p_user_id"], "email": p["p_email"].lower(), "full_name": p["p_full_name"],
            "role": p["p_role"], "campus_id": p.get("p_campus"), "department_id": None,
            "cross_campus_record_access": False,
        }
        self.tables["profiles"].append(profile)
        self._audit(p["p_actor"], p["p_email"], p["p_role"], "invited", None, p["p_user_id"])
        return {k: profile[k] for k in ("id", "email", "full_name", "role", "campus_id", "department_id")}

    def _provisioning_complete(self, p):
        actor = self._actor(p["p_actor"])
        if actor is None or actor["role"] != "authority" or not actor.get("campus_id"):
            raise DataServiceError(400, "provisioning_not_permitted")
        if p["p_role"] not in ("student", "faculty"):
            raise DataServiceError(400, "provisioning_invalid_role")
        dept = p["p_department"]
        if dept and not any(d["id"] == dept and d["campus_id"] == actor["campus_id"] for d in self.tables["departments"]):
            raise DataServiceError(400, "provisioning_department_not_in_campus")
        profile = {
            "id": p["p_user_id"], "email": p["p_email"].lower(), "full_name": p["p_full_name"],
            "role": p["p_role"], "campus_id": actor["campus_id"], "department_id": dept,
            "cross_campus_record_access": False,
        }
        self.tables["profiles"].append(profile)
        self._audit(p["p_actor"], p["p_email"], p["p_role"], "invited", None, p["p_user_id"])
        return {k: profile[k] for k in ("id", "email", "full_name", "role", "campus_id", "department_id")}

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
                    raise DataServiceError(400, '{"message":"document_not_publishable"}')
                row["publication_status"] = "published"
                if row.get("replaces_document_id"):
                    for old in self.tables["documents"]:
                        if old["id"] == row["replaces_document_id"] and old["publication_status"] == "published":
                            old["publication_status"] = "archived"
                return copy.deepcopy(row)
        raise DataServiceError(400, '{"message":"document_not_publishable"}')

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
        if function in self.rpc_responses:
            return copy.deepcopy(self.rpc_responses[function])
        if function == "staff_dashboard_stats":
            return {}
        return copy.deepcopy(self.rpc_rows)


class FakeAI:
    """Deterministic embeddings and a scripted answer. Records what was sent."""

    def __init__(self, reply: str = "", fail_embed: bool = False):
        self.reply = reply
        self.fail_embed = fail_embed
        self.embedded: list[str] = []
        self.completions: list[tuple[str, str]] = []

    async def embed_documents(self, texts):
        if self.fail_embed:
            from app.ai.gemini_client import AIServiceError

            raise AIServiceError("embedding failed")
        self.embedded.extend(texts)
        return [self._vector(t) for t in texts]

    async def embed_query(self, text):
        return self._vector(text)

    @staticmethod
    def _vector(text):
        return [float(len(text) % 7) / 10 + 0.01] * 1536

    async def complete(self, system, user):
        self.completions.append((system, user))
        return self.reply


class FakeAccountDirectory:
    """Records invitations instead of sending them. Never contacts any service."""

    def __init__(self, invite_error=None, delete_error=None):
        self.invites: list[tuple[str, str, Any]] = []
        self.deleted: list[Any] = []
        self.invite_error = invite_error
        self.delete_error = delete_error

    async def invite_user(self, email, full_name):
        if self.invite_error:
            raise self.invite_error
        user_id = uuid4()
        self.invites.append((email, full_name, user_id))
        return user_id

    async def delete_user(self, user_id):
        if self.delete_error:
            raise self.delete_error
        self.deleted.append(user_id)
