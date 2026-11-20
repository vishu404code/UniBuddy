"""Private chat history notes: ranking, gradual pruning, correction and deletion, plus one presentation style.

A note is a short summary of a Student's older chats (see chat_retention). Notes are kept for the Student to
read, correct and delete. They are NEVER sent to a model and never influence an answer: an answer's facts come
only from retrieved, cited official documents. The only thing a Student's settings can change in an answer is
the presentation style (see get_answer_style), chosen from a fixed list of codes.

Everything here is off unless CHAT_MEMORY_CONTEXT_ENABLED is true. With the flag off, nothing in this module
queries or changes the memory table (chat_summaries) or the style table.

Ranking (higher is kept and shown first):
- last activity = the later of last_used_at (last time the note helped an answer) and last_message_at.
- decay = 0.5 ** (idle_days / 365). Without use, a note loses half its weight each year.
- score = decay * (0.35 + 0.45 * min(1, use_count / 3)), plus 0.2 if the note is 'important'.
- 'pinned' notes always rank first and are never pruned.

Pruning is gradual and bounded. An unpinned, unimportant note is removed only when it has been idle for at
least MIN_AGE_DAYS and its score is below PRUNE_BELOW. Without use that happens after about 295 idle days;
used once, after about 16 idle months; used three times or more, after about 2 years. A recently used
note keeps a high score, so a useful six-month-old note stays. Each run removes at most MAX_PRUNE_PER_RUN
notes, keeps at least MIN_KEEP, and a failure removes nothing.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.ai.rag import ANSWER_STYLES, Answer
from app.config import settings
from app.schemas.auth import CurrentUser
from app.services.chat_retention import redact
from app.services.documents import DocumentError, DocumentNotFound
from app.services.postgres_client import PostgresClient

RECENCY_WEIGHT = 0.35
HALF_LIFE_DAYS = 365.0
USAGE_WEIGHT = 0.45
USAGE_SATURATION = 3
IMPORTANT_BONUS = 0.2
PRUNE_BELOW = 0.2
MIN_AGE_DAYS = 90
MAX_PRUNE_PER_RUN = 10
MIN_KEEP = 20
MEMORY_CONTEXT_MIN_SCORE = 0.2
MAX_TEXT_CHARS = 1500
IMPORTANCE_VALUES = ("normal", "important", "pinned")
logger = logging.getLogger("unibuddy.chat_memory")


class MemoryDisabled(Exception):
    """A memory operation was requested while CHAT_MEMORY_CONTEXT_ENABLED is off."""


def memory_enabled() -> bool:
    return bool(settings.chat_memory_context_enabled)


def _require_enabled() -> None:
    if not memory_enabled():
        raise MemoryDisabled("Personal memory is turned off")


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def last_activity(row: dict[str, Any]) -> datetime:
    seen = _as_datetime(row["last_message_at"])
    if row.get("last_used_at"):
        seen = max(seen, _as_datetime(row["last_used_at"]))
    return seen


def idle_days(row: dict[str, Any], now: datetime) -> float:
    return max(0.0, (now - last_activity(row)).total_seconds() / 86400.0)


def memory_score(row: dict[str, Any], now: datetime) -> float:
    decay = 0.5 ** (idle_days(row, now) / HALF_LIFE_DAYS)
    usefulness = min(1.0, int(row.get("use_count") or 0) / USAGE_SATURATION)
    importance = IMPORTANT_BONUS if row.get("importance") == "important" else 0.0
    return decay * (RECENCY_WEIGHT + USAGE_WEIGHT * usefulness) + importance


def rank_memories(rows: list[dict[str, Any]], now: datetime, limit: int) -> list[dict[str, Any]]:
    """Pinned first, then by score, then by most recent chat. Returns at most limit rows."""
    def key(row):
        pinned = 1 if row.get("importance") == "pinned" else 0
        return (pinned, memory_score(row, now), _as_datetime(row["last_message_at"]))

    return sorted(rows, key=key, reverse=True)[:limit]


def prune_candidates(rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Memories that may be removed this run, lowest score first. Pure: decides nothing on its own."""
    if len(rows) <= MIN_KEEP:
        return []
    candidates = [
        row for row in rows
        if row.get("importance") == "normal"
        and idle_days(row, now) >= MIN_AGE_DAYS
        and memory_score(row, now) < PRUNE_BELOW
    ]
    candidates.sort(key=lambda row: memory_score(row, now))
    allowed = len(rows) - MIN_KEEP
    return candidates[: min(MAX_PRUNE_PER_RUN, allowed)]


@dataclass(frozen=True)
class PruneResult:
    status: str
    removed: int = 0
    reason: str | None = None


async def _own_memories(sb: PostgresClient, user: CurrentUser) -> list[dict[str, Any]]:
    return await sb.select_service(
        "chat_summaries",
        {
            "select": "id,summary,importance,use_count,last_used_at,corrected_at,last_message_at,created_at",
            "user_id": f"eq.{user.id}",
            "order": "last_message_at.desc",
            "limit": "500",
        },
    )


async def prune_student_memories(*, sb: PostgresClient, user: CurrentUser, now: datetime | None = None) -> PruneResult:
    """One bounded pass for one Student. With the flag off this returns at once without a query.
    Any failure leaves every memory in place and is reported, not raised: the caller is a normal page load."""
    if not memory_enabled():
        return PruneResult(status="disabled")
    now = now or datetime.now(timezone.utc)
    try:
        rows = await _own_memories(sb, user)
        candidates = prune_candidates(rows, now)
        if not candidates:
            return PruneResult(status="nothing_to_prune")
        await sb.delete_service(
            "chat_summaries",
            {"user_id": f"eq.{user.id}", "id": f"in.({','.join(str(c['id']) for c in candidates)})"},
        )
        return PruneResult(status="pruned", removed=len(candidates))
    except Exception as error:  # noqa: BLE001 - pruning is maintenance; it must never fail a page load
        logger.warning("memory pruning did not finish (%s); memories were left in place", type(error).__name__)
        return PruneResult(status="error", reason="database unavailable; nothing was removed")


async def list_memories(*, sb: PostgresClient, access_token: str, limit: int = 50) -> list[dict[str, Any]]:
    """The caller's own memories, read under their own access (RLS). Nothing from another Student is returned."""
    _require_enabled()
    rows, _ = await sb.select_page_as_user(
        access_token,
        "chat_summaries",
        {
            "select": "id,summary,importance,use_count,last_used_at,corrected_at,last_message_at",
            "order": "last_message_at.desc",
        },
        limit,
        0,
    )
    return rows


async def _owned_memory(sb: PostgresClient, user: CurrentUser, memory_id) -> dict[str, Any]:
    rows = await sb.select_service(
        "chat_summaries", {"select": "id,user_id", "id": f"eq.{memory_id}", "user_id": f"eq.{user.id}"}
    )
    if not rows:
        raise DocumentNotFound("Memory not found")
    return rows[0]


async def correct_memory(
    *, sb: PostgresClient, user: CurrentUser, memory_id, text: str | None = None,
    importance: str | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    """The Student corrects the text and/or sets importance. Other Students' memories are reported as not found."""
    _require_enabled()
    now = now or datetime.now(timezone.utc)
    await _owned_memory(sb, user, memory_id)
    values: dict[str, Any] = {}
    if text is not None:
        cleaned = redact(" ".join(text.split()))[:MAX_TEXT_CHARS].strip()
        if not cleaned:
            raise DocumentError("A memory cannot be empty")
        values["summary"] = cleaned
        values["corrected_at"] = now.isoformat()
    if importance is not None:
        if importance not in IMPORTANCE_VALUES:
            raise DocumentError("importance must be normal, important or pinned")
        values["importance"] = importance
    if not values:
        raise DocumentError("Nothing to change")
    await sb.update_service("chat_summaries", {"id": f"eq.{memory_id}", "user_id": f"eq.{user.id}"}, values)
    rows = await sb.select_service(
        "chat_summaries",
        {"select": "id,summary,importance,use_count,corrected_at,last_message_at", "id": f"eq.{memory_id}"},
    )
    return rows[0]


async def delete_memory(*, sb: PostgresClient, user: CurrentUser, memory_id) -> None:
    _require_enabled()
    await _owned_memory(sb, user, memory_id)
    await sb.delete_service("chat_summaries", {"id": f"eq.{memory_id}", "user_id": f"eq.{user.id}"})


# --- Answer style: the only thing personal memory may change in an answer ------------------------------------
#
# Chat history never reaches an answer. A Student may choose one fixed presentation style, stored as a code
# (see ANSWER_STYLES in app.ai.rag). Its text is server-side and says nothing about content, so it cannot add
# or change a college fact. With the flag off there is no read and no write.

STYLE_TABLE = "chat_answer_preferences"


async def get_answer_style(*, sb: PostgresClient, access_token: str, user: CurrentUser) -> str | None:
    """The Student's chosen style, read under their own access. A failure, or a value not in ANSWER_STYLES,
    gives no style, so the answer is simply unchanged."""
    if not memory_enabled():
        return None
    try:
        rows = await sb.select_as_user(
            access_token, STYLE_TABLE, {"select": "style", "user_id": f"eq.{user.id}", "limit": "1"}
        )
    except Exception:  # noqa: BLE001 - a presentation preference must never stop an answer
        logger.warning("answer style could not be read; the answer uses the default style")
        return None
    style = rows[0].get("style") if rows else None
    return style if style in ANSWER_STYLES else None


async def set_answer_style(*, sb: PostgresClient, user: CurrentUser, style: str, now: datetime | None = None) -> str:
    """Stores the Student's style. Only a code from ANSWER_STYLES is accepted; free text is refused."""
    _require_enabled()
    if style not in ANSWER_STYLES:
        raise DocumentError("style must be one of: " + ", ".join(sorted(ANSWER_STYLES)))
    now = now or datetime.now(timezone.utc)
    values = {"style": style, "updated_at": now.isoformat()}
    existing = await sb.select_service(STYLE_TABLE, {"select": "user_id", "user_id": f"eq.{user.id}", "limit": "1"})
    if existing:
        await sb.update_service(STYLE_TABLE, {"user_id": f"eq.{user.id}"}, values)
    else:
        await sb.insert_service(STYLE_TABLE, [{"user_id": str(user.id), **values}])
    return style


# --- Recall of the Student's own chats -----------------------------------------------------------------------
#
# Used only when the Student explicitly asks about their own earlier chats (AskRequest.recall_own_chats) and the
# flag is on. The reply is built from the Student's own saved summaries. No document and no model is involved,
# and the reply is labelled as not an official source. Summaries that contain a number, a date or a month are
# withheld: those are the likeliest to carry a college fact, and college facts come only from official documents.

RECALL_LIMIT = 5
NO_RECALL = (
    "I couldn't find that in your earlier chats. Official answers come from approved university documents, "
    "so ask the question again without recall for those."
)
_DATE_OR_NUMBER = re.compile(
    r"\d|\b(?:january|february|march|april|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday)\b",
    re.IGNORECASE,
)


async def recall_answer(*, sb: PostgresClient, access_token: str, user: CurrentUser) -> Answer:
    """What the Student's own earlier chats recorded, from their own summaries (read under their own access)."""
    try:
        rows = await list_memories(sb=sb, access_token=access_token, limit=50)
    except Exception:  # noqa: BLE001 - recall is optional; a failure gives the plain "not found" reply
        logger.warning("earlier chats could not be read for recall")
        return Answer(text=NO_RECALL, citations=[], abstained=True)
    kept = [row for row in rows if not _DATE_OR_NUMBER.search(row["summary"])][:RECALL_LIMIT]
    if not kept:
        return Answer(text=NO_RECALL, citations=[], abstained=True)
    lines = []
    for row in kept:
        when = _as_datetime(row["last_message_at"]).date().isoformat()
        text = " ".join(str(row["summary"]).split()).lstrip("-• ").strip()
        lines.append(f"- {text} (chat from {when})")
    text = "From your earlier chats (your own saved summaries, not official sources):\n" + "\n".join(lines)
    return Answer(text=text, citations=[], abstained=False)
