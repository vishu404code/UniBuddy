"""Filter options for each campus: academic years, batch years and sections. Authority manages them.
Faculty select from the active ones. Anything already used is deactivated, never hard-deleted."""

import re
from typing import Any
from uuid import UUID, uuid4

from app.schemas.auth import CurrentUser
from app.services.documents import DocumentConflict, DocumentError, DocumentForbidden, DocumentNotFound
from app.services.errors import DataServiceError
from app.services.postgres_client import PostgresClient

KINDS = ("academic_year", "batch", "section")
KIND_LABELS = {"academic_year": "academic year", "batch": "batch year", "section": "section"}
MAX_LENGTH = {"academic_year": 20, "batch": 4, "section": 10}
BATCH_PATTERN = re.compile(r"^[0-9]{4}$")
# Where each option value may already be stored. Any match means the option is in use.
USAGE_CHECKS = {
    "academic_year": (("documents", "academic_year"), ("announcements", "academic_year"), ("profiles", "academic_year")),
    "batch": (("documents", "batch_year"), ("announcements", "batch_year"), ("profiles", "batch_year")),
    "section": (("documents", "section"), ("announcements", "section"), ("profiles", "section")),
}


def _require_authority(user: CurrentUser) -> None:
    if user.role != "authority":
        raise DocumentForbidden("Only authority can manage filter options")
    if user.campus_id is None:
        raise DocumentForbidden("Your account has no campus assigned")


def clean_option(kind: str, value: str) -> str:
    if kind not in KINDS:
        raise DocumentError("Unknown filter option")
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > MAX_LENGTH[kind]:
        raise DocumentError(f"A {KIND_LABELS[kind]} must be 1 to {MAX_LENGTH[kind]} characters")
    if kind == "batch":
        if not BATCH_PATTERN.match(cleaned) or not (2000 <= int(cleaned) <= 2100):
            raise DocumentError("A batch year must be a four-digit year between 2000 and 2100")
    return cleaned


async def list_options(sb: PostgresClient, user: CurrentUser, *, include_inactive: bool) -> list[dict[str, Any]]:
    if user.campus_id is None:
        return []
    params = {
        "select": "id,kind,value,active,created_at",
        "campus_id": f"eq.{user.campus_id}",
        "order": "kind.asc,value.asc",
    }
    if not include_inactive:
        params["active"] = "eq.true"
    return await sb.select_service("filter_options", params)


async def _load_campus_option(sb: PostgresClient, user: CurrentUser, option_id: UUID) -> dict[str, Any]:
    rows = await sb.select_service(
        "filter_options", {"select": "*", "id": f"eq.{option_id}", "campus_id": f"eq.{user.campus_id}"}
    )
    if not rows:
        raise DocumentNotFound("Filter option not found")
    return rows[0]


async def _ensure_free(sb: PostgresClient, user: CurrentUser, kind: str, value: str, except_id: UUID | None) -> None:
    rows = await sb.select_service(
        "filter_options", {"select": "id,value", "campus_id": f"eq.{user.campus_id}", "kind": f"eq.{kind}"}
    )
    for row in rows:
        same = str(row["value"]).strip().lower() == value.lower()
        if same and str(row["id"]) != str(except_id or ""):
            raise DocumentConflict(f"This {KIND_LABELS[kind]} is already in the list")


async def create_option(sb: PostgresClient, user: CurrentUser, kind: str, value: str) -> dict[str, Any]:
    _require_authority(user)
    cleaned = clean_option(kind, value)
    await _ensure_free(sb, user, kind, cleaned, None)
    option_id = uuid4()
    try:
        await sb.insert_service("filter_options", [{
            "id": str(option_id),
            "campus_id": str(user.campus_id),
            "kind": kind,
            "value": cleaned,
            "active": True,
            "created_by": str(user.id),
        }])
    except DataServiceError as exc:
        if exc.status_code == 409:
            raise DocumentConflict(f"This {KIND_LABELS[kind]} is already in the list") from exc
        raise
    rows = await sb.select_service("filter_options", {"select": "*", "id": f"eq.{option_id}"})
    return rows[0]


async def set_option_active(sb: PostgresClient, user: CurrentUser, option_id: UUID, active: bool) -> dict[str, Any]:
    _require_authority(user)
    await _load_campus_option(sb, user, option_id)
    await sb.update_service("filter_options", {"id": f"eq.{option_id}"}, {"active": active})
    rows = await sb.select_service("filter_options", {"select": "*", "id": f"eq.{option_id}"})
    return rows[0]


async def _is_used(sb: PostgresClient, user: CurrentUser, kind: str, value: str) -> bool:
    """True when a document, announcement or student profile on this campus already carries the value."""
    wanted = f"eq.{int(value)}" if kind == "batch" else f"eq.{value}"
    for table, column in USAGE_CHECKS[kind]:
        rows = await sb.select_service(
            table, {"select": "id", "campus_id": f"eq.{user.campus_id}", column: wanted, "limit": "1"}
        )
        if rows:
            return True
    return False


async def remove_option(sb: PostgresClient, user: CurrentUser, option_id: UUID) -> dict[str, Any]:
    """Deletes an unused option. A used option is deactivated instead, so existing records keep their value."""
    _require_authority(user)
    option = await _load_campus_option(sb, user, option_id)
    if not await _is_used(sb, user, option["kind"], str(option["value"])):
        try:
            await sb.delete_service("filter_options", {"id": f"eq.{option_id}"})
            return {"action": "deleted", "id": str(option_id)}
        except DataServiceError:
            pass
    await sb.update_service("filter_options", {"id": f"eq.{option_id}"}, {"active": False})
    return {"action": "deactivated", "id": str(option_id)}
