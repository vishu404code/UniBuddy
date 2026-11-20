"""The 72-hour chat window, and private summaries of older chats.

Raw messages older than 72 hours are summarized and then removed, one bounded batch at a time.
The order is fixed so a retry is always safe:

  1. Choose a batch of old messages (never one that a forwarded ticket points at).
  2. Its batch_key is a hash of the message ids. If a summary with that key exists, reuse it;
     otherwise write one.  The unique (user_id, batch_key) makes a second write harmless.
  3. Only after the summary is saved, delete those messages.

If summarizing fails, nothing is deleted. If deleting fails part way, the next run picks up the same
batch, finds its summary and deletes the rest. No summary is ever created twice for the same messages.

Scheduling: there is no background job on the free hosting plan. Cleanup runs when a Student opens
their chat history, one batch per request, so an old backlog is cleared over several visits.
"""

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from app.ai.gemini_client import AIServiceError
from app.config import settings
from app.schemas.auth import CurrentUser
from app.services.errors import DataServiceError
from app.services.postgres_client import PostgresClient

WINDOW = timedelta(hours=72)
BATCH_MESSAGES = 40       # raw messages summarized and removed per run
SCAN_MESSAGES = 200       # old messages read per run, so ticket-linked ones can be skipped
CONVERSATION_SCAN = 20    # conversations looked at per run
SUMMARY_MAX_CHARS = 1200
logger = logging.getLogger("unibuddy.chat_retention")

# Anything that looks like a secret or a personal contact detail is removed before it is sent to the
# model and again from the model's answer.
_REDACTIONS = [
    # A keyword and the next few words after it (the value usually follows): "password is hunter2".
    (re.compile(r"(?i)(password|passcode|otp|token|api[ _-]?key|secret|bearer|credential)s?\b(?:[\s:=]+\S+){0,4}"), "[removed]"),
    # Any long run of token-like characters.
    (re.compile(r"[A-Za-z0-9_\-]{24,}"), "[removed]"),
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "[email]"),
    (re.compile(r"\+?\d[\d \-]{8,}\d"), "[number]"),
]

SYSTEM_PROMPT = (
    "You write private notes about a university student's chats with a campus assistant, so the assistant "
    "can follow up later. Write at most six short bullet points: the topics asked about, facts the student "
    "shared that are not secrets, decisions, and open questions. Never include passwords, tokens, keys, "
    "login details, account or card numbers, phone numbers, email addresses or other personal identifiers. "
    "Do not quote the messages. Never record a college fact, fee, date, deadline, exam, rule or policy that the "
    "assistant stated: record only what the Student asked about or said about themselves."
)


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def cutoff_for(now: datetime) -> datetime:
    return now - WINDOW


def batch_key(message_ids: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(message_ids)).encode("utf-8")).hexdigest()


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _transcript(batch: list[dict[str, Any]]) -> str:
    lines = []
    for message in batch:
        who = "Student" if message["role"] == "user" else "Assistant"
        lines.append(f"{who}: {redact(str(message['content']))[:600]}")
    return "\n".join(lines)


async def _ticket_linked_ids(sb: PostgresClient, message_ids: list[str]) -> set[str]:
    if not message_ids:
        return set()
    rows = await sb.select_service(
        "tickets",
        {"select": "source_message_id", "source_message_id": f"in.({','.join(message_ids)})"},
    )
    return {str(row["source_message_id"]) for row in rows if row.get("source_message_id")}


async def _next_old_batch(sb: PostgresClient, user: CurrentUser, cutoff: datetime):
    conversations = await sb.select_service(
        "conversations",
        {"select": "id,created_at", "user_id": f"eq.{user.id}", "order": "created_at.asc", "limit": str(CONVERSATION_SCAN)},
    )
    for conversation in conversations:
        rows = await sb.select_service(
            "messages",
            {
                "select": "id,role,content,created_at",
                "conversation_id": f"eq.{conversation['id']}",
                "created_at": f"lt.{cutoff.isoformat()}",
                "order": "created_at.asc",
                "limit": str(SCAN_MESSAGES),
            },
        )
        if not rows:
            continue
        linked = await _ticket_linked_ids(sb, [str(r["id"]) for r in rows])
        batch = [r for r in rows if str(r["id"]) not in linked][:BATCH_MESSAGES]
        if batch:
            return batch, conversation
    return [], None


async def summarize(ai: Any, batch: list[dict[str, Any]]) -> str:
    text = await ai.complete(SYSTEM_PROMPT, _transcript(batch))
    cleaned = redact((text or "").strip())[:SUMMARY_MAX_CHARS].strip()
    if not cleaned:
        raise AIServiceError("empty summary")
    return cleaned


async def _drop_empty_conversation(sb: PostgresClient, conversation: dict[str, Any], cutoff: datetime) -> bool:
    """A conversation that is older than the window and has no messages left is removed."""
    created = _as_datetime(conversation["created_at"])
    if created >= cutoff:
        return False
    left = await sb.select_service(
        "messages", {"select": "id", "conversation_id": f"eq.{conversation['id']}", "limit": "1"}
    )
    if left:
        return False
    await sb.delete_service("conversations", {"id": f"eq.{conversation['id']}"})
    return True


async def tidy_student_chats(*, sb: PostgresClient, ai: Any | None, user: CurrentUser, now: datetime | None = None) -> dict[str, Any]:
    """One bounded pass for one Student. Returns what happened; raises only on database errors."""
    now = now or datetime.now(timezone.utc)
    cutoff = cutoff_for(now)
    batch, conversation = await _next_old_batch(sb, user, cutoff)
    if not batch:
        return {"status": "nothing_to_do"}

    ids = [str(m["id"]) for m in batch]
    key = batch_key(ids)
    existing = await sb.select_service(
        "chat_summaries", {"select": "id", "user_id": f"eq.{user.id}", "batch_key": f"eq.{key}", "limit": "1"}
    )
    created = False
    if not existing:
        if ai is None:
            return {"status": "deferred", "reason": "AI service not configured; nothing was removed"}
        try:
            summary = await summarize(ai, batch)
        except AIServiceError:
            return {"status": "deferred", "reason": "summary unavailable; nothing was removed"}
        try:
            await sb.insert_service("chat_summaries", [{
                "id": str(uuid4()),
                "user_id": str(user.id),
                "conversation_id": str(conversation["id"]),
                "batch_key": key,
                "message_count": len(batch),
                "first_message_at": batch[0]["created_at"],
                "last_message_at": batch[-1]["created_at"],
                "summary": summary,
            }])
            created = True
        except DataServiceError as exc:
            if exc.status_code != 409:
                raise  # a concurrent run saved the same summary; that is the outcome we want

    await sb.delete_service("messages", {"id": f"in.({','.join(ids)})"})
    conversation_removed = await _drop_empty_conversation(sb, conversation, cutoff)
    return {
        "status": "summarized",
        "summary_created": created,
        "messages_removed": len(ids),
        "conversation_removed": conversation_removed,
    }


async def tidy_student_chats_safely(**kwargs: Any) -> dict[str, Any]:
    """Used on the history request: a cleanup problem must never break the Student's history."""
    try:
        return await tidy_student_chats(**kwargs)
    except Exception:  # noqa: BLE001 - logged; the history request itself still succeeds
        logger.warning("chat tidy-up did not finish; it will be retried on the next visit")
        return {"status": "error"}


async def recent_summaries(sb: PostgresClient, access_token: str, limit: int = 5) -> list[dict[str, Any]]:
    """The caller's own summaries, newest first. Row-level security returns nothing for anyone else.
    Nothing in the chat answer path reads these. With CHAT_MEMORY_CONTEXT_ENABLED off this does not query."""
    if not settings.chat_memory_context_enabled:
        return []
    rows, _ = await sb.select_page_as_user(
        access_token, "chat_summaries", {"select": "summary,last_message_at", "order": "last_message_at.desc"}, limit, 0
    )
    return rows
