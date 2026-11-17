"""The 72-hour chat window, private summaries of older chats, and safe cleanup.

Fixtures only: students, conversations and messages are created in memory by this file. Times are
relative to a fixed clock so the cutoff is exact. No network calls; the AI model is a fake."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.ai.gemini_client import AIServiceError
from app.routes.chat import list_conversations, list_messages
from app.services.chat_retention import (
    BATCH_MESSAGES,
    SUMMARY_MAX_CHARS,
    cutoff_for,
    recent_summaries,
    redact,
    tidy_student_chats,
    tidy_student_chats_safely,
)
from app.services.errors import DataServiceError
from tests.conftest import make_profile
from tests.fakes import FakeAI, FakeDataClient

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
MIGRATION = Path(__file__).resolve().parents[1] / "app" / "db" / "migrations" / "20261117140000_chat_summaries.sql"


def _iso(hours_before_now: float) -> str:
    return (NOW - timedelta(hours=hours_before_now)).isoformat()


def _student(sb, name="Fixture Student"):
    student = make_profile(str(uuid4()), role="student", campus_id=str(uuid4()))
    sb.tables["profiles"].append({"id": str(student.id), "email": f"{student.id}@example.edu", "full_name": name,
                                  "role": "student", "campus_id": str(student.campus_id)})
    return student


def _conversation(sb, student, created_hours_ago=200):
    conversation_id = str(uuid4())
    sb.tables["conversations"].append({"id": conversation_id, "user_id": str(student.id), "title": "fixture",
                                       "created_at": _iso(created_hours_ago), "updated_at": _iso(created_hours_ago)})
    return conversation_id


def _message(sb, conversation_id, hours_before_now, content="fixture question", role="user"):
    message_id = str(uuid4())
    sb.tables["messages"].append({"id": message_id, "conversation_id": conversation_id, "role": role,
                                  "content": content, "citations": [], "created_at": _iso(hours_before_now)})
    return message_id


# --- The 72-hour cutoff ------------------------------------------------------------------------

def test_cutoff_is_exactly_seventy_two_hours_before_now():
    assert cutoff_for(NOW) == NOW - timedelta(hours=72)


@pytest.mark.asyncio
async def test_history_shows_only_messages_from_the_last_72_hours(monkeypatch):
    sb = FakeDataClient()
    student = _student(sb)
    conversation = _conversation(sb, student)
    old = _message(sb, conversation, 80)
    recent = _message(sb, conversation, 2)
    monkeypatch.setattr("app.routes.chat.datetime", _FixedClock)

    page = await list_messages(conversation_id=UUID(conversation), session=_session(student), limit=50, offset=0, sb=sb)

    assert [str(m.id) for m in page.items] == [recent]
    assert old not in [str(m.id) for m in page.items]


@pytest.mark.asyncio
async def test_conversation_list_includes_only_chats_with_recent_messages(monkeypatch):
    sb = FakeDataClient()
    student = _student(sb)
    stale = _conversation(sb, student)
    _message(sb, stale, 100)
    fresh = _conversation(sb, student)
    _message(sb, fresh, 3)
    monkeypatch.setattr("app.routes.chat.datetime", _FixedClock)
    monkeypatch.setattr("app.routes.chat.get_ai_client", _no_ai)

    page = await list_conversations(session=_session(student), limit=20, offset=0, sb=sb)

    assert [str(c.id) for c in page.items] == [fresh]


# --- Summaries: content, ownership, privacy -------------------------------------------------------

@pytest.mark.asyncio
async def test_old_messages_are_summarized_saved_and_then_removed():
    sb = FakeDataClient()
    student = _student(sb)
    conversation = _conversation(sb, student)
    for hours in (90, 88, 86):
        _message(sb, conversation, hours, "Is the library open on Sunday?")
    _message(sb, conversation, 1, "recent question stays")
    ai = FakeAI(reply="- Asked about library hours on Sunday.")

    result = await tidy_student_chats(sb=sb, ai=ai, user=student, now=NOW)

    assert result["status"] == "summarized"
    assert result["messages_removed"] == 3
    [summary] = sb.tables["chat_summaries"]
    assert summary["user_id"] == str(student.id)
    assert "library hours" in summary["summary"]
    assert [m["content"] for m in sb.tables["messages"]] == ["recent question stays"]


@pytest.mark.asyncio
async def test_each_run_takes_at_most_one_bounded_batch():
    sb = FakeDataClient()
    student = _student(sb)
    conversation = _conversation(sb, student)
    for i in range(BATCH_MESSAGES + 15):
        _message(sb, conversation, 100 + i)

    result = await tidy_student_chats(sb=sb, ai=FakeAI(reply="- Notes."), user=student, now=NOW)

    assert result["messages_removed"] == BATCH_MESSAGES
    assert len(sb.tables["messages"]) == 15


@pytest.mark.asyncio
async def test_a_summary_is_never_longer_than_its_limit_and_secrets_are_removed_before_saving():
    sb = FakeDataClient()
    student = _student(sb)
    conversation = _conversation(sb, student)
    _message(sb, conversation, 90, "my password is hunter2-fixture and token abcdef0123456789abcdef0123456789")
    leaky_reply = "- Student wrote to someone@example.edu about a login. " + "x" * (SUMMARY_MAX_CHARS * 2)
    ai = FakeAI(reply=leaky_reply)

    await tidy_student_chats(sb=sb, ai=ai, user=student, now=NOW)

    [summary] = sb.tables["chat_summaries"]
    assert len(summary["summary"]) <= SUMMARY_MAX_CHARS
    assert "someone@example.edu" not in summary["summary"]
    # The model never received the password or the token.
    sent = "\n".join(user_prompt for _, user_prompt in ai.completions)
    assert "hunter2-fixture" not in sent
    assert "abcdef0123456789abcdef0123456789" not in sent


def test_redaction_removes_credentials_contacts_and_long_tokens():
    text = redact("password: hunter2 and otp 123456 mail a.b@x.edu call +91 98765 43210 key ABCDEFGHIJKLMNOPQRSTUVWXYZ123456")
    for leaked in ("hunter2", "123456", "a.b@x.edu", "98765", "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"):
        assert leaked not in text


@pytest.mark.asyncio
async def test_summaries_are_private_to_the_student_who_owns_them():
    token_by_user = {}

    def visible(token, table, row):
        # Stands in for the policy chat_summaries_select_owner: a row is visible to its owner only.
        return row.get("user_id") == token

    sb = FakeDataClient(visible=visible)
    alice = _student(sb, "Alice")
    bob = _student(sb, "Bob")
    conversation = _conversation(sb, alice)
    _message(sb, conversation, 90, "alice question")
    await tidy_student_chats(sb=sb, ai=FakeAI(reply="- Alice asked a question."), user=alice, now=NOW)

    assert len(await recent_summaries(sb, str(alice.id))) == 1
    assert await recent_summaries(sb, str(bob.id)) == []


def test_the_policy_limits_summaries_to_their_owner_and_grants_no_other_role():
    sql = MIGRATION.read_text()
    assert "create policy \"chat_summaries_select_owner\"" in sql
    assert "using (user_id = unibuddy_auth.user_id())" in sql
    assert "grant select on public.chat_summaries to authenticated" in sql
    assert "to anon" not in sql
    assert sql.count("create policy") == 1  # no other role has a policy on summaries


# --- Cleanup safety and retries --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_failed_summary_save_removes_nothing():
    sb = FakeDataClient()
    student = _student(sb)
    conversation = _conversation(sb, student)
    _message(sb, conversation, 90)
    original_insert = sb.insert_service

    async def fail_on_summary(table, rows):
        if table == "chat_summaries":
            raise DataServiceError(503, "database unavailable")
        await original_insert(table, rows)

    sb.insert_service = fail_on_summary
    with pytest.raises(DataServiceError):
        await tidy_student_chats(sb=sb, ai=FakeAI(reply="- Notes."), user=student, now=NOW)

    assert sb.tables["chat_summaries"] == []
    assert len(sb.tables["messages"]) == 1


@pytest.mark.asyncio
async def test_a_retry_after_a_failed_delete_does_not_create_a_second_summary():
    sb = FakeDataClient()
    student = _student(sb)
    conversation = _conversation(sb, student)
    _message(sb, conversation, 90)
    _message(sb, conversation, 91)
    original_delete = sb.delete_service
    calls = {"n": 0}

    async def flaky_delete(table, filters):
        if table == "messages" and calls["n"] == 0:
            calls["n"] += 1
            raise DataServiceError(503, "database unavailable")
        await original_delete(table, filters)

    sb.delete_service = flaky_delete
    ai = FakeAI(reply="- Notes.")
    with pytest.raises(DataServiceError):
        await tidy_student_chats(sb=sb, ai=ai, user=student, now=NOW)
    assert len(sb.tables["chat_summaries"]) == 1
    assert len(sb.tables["messages"]) == 2

    result = await tidy_student_chats(sb=sb, ai=ai, user=student, now=NOW)

    assert result["summary_created"] is False
    assert len(sb.tables["chat_summaries"]) == 1
    assert sb.tables["messages"] == []
    assert len(ai.completions) == 1  # the second run reused the saved summary and did not call the model


@pytest.mark.asyncio
async def test_a_failed_model_call_keeps_the_messages_for_the_next_visit():
    sb = FakeDataClient()
    student = _student(sb)
    conversation = _conversation(sb, student)
    _message(sb, conversation, 90)

    class BrokenAI(FakeAI):
        async def complete(self, system, user):
            raise AIServiceError("model unavailable")

    result = await tidy_student_chats(sb=sb, ai=BrokenAI(), user=student, now=NOW)

    assert result["status"] == "deferred"
    assert sb.tables["chat_summaries"] == []
    assert len(sb.tables["messages"]) == 1


@pytest.mark.asyncio
async def test_messages_behind_a_forwarded_ticket_are_kept_because_the_ticket_points_at_them():
    sb = FakeDataClient()
    student = _student(sb)
    conversation = _conversation(sb, student)
    forwarded = _message(sb, conversation, 90, "question sent to faculty")
    _message(sb, conversation, 91, "ordinary old question")
    sb.tables["tickets"].append({"id": str(uuid4()), "source_message_id": forwarded, "student_id": str(student.id)})

    await tidy_student_chats(sb=sb, ai=FakeAI(reply="- Notes."), user=student, now=NOW)

    remaining = [m["id"] for m in sb.tables["messages"]]
    assert remaining == [forwarded]


@pytest.mark.asyncio
async def test_without_an_ai_service_old_chats_wait_and_the_history_request_still_works(monkeypatch):
    sb = FakeDataClient()
    student = _student(sb)
    conversation = _conversation(sb, student)
    _message(sb, conversation, 90)
    _message(sb, conversation, 2)
    monkeypatch.setattr("app.routes.chat.datetime", _FixedClock)
    monkeypatch.setattr("app.routes.chat.get_ai_client", _no_ai)

    page = await list_conversations(session=_session(student), limit=20, offset=0, sb=sb)

    assert [str(c.id) for c in page.items] == [conversation]
    assert len(sb.tables["messages"]) == 2


@pytest.mark.asyncio
async def test_a_cleanup_error_never_breaks_the_history_request():
    sb = FakeDataClient()
    student = _student(sb)

    async def broken_select(table, params):
        raise RuntimeError("unexpected")

    sb.select_service = broken_select
    result = await tidy_student_chats_safely(sb=sb, ai=None, user=student)
    assert result == {"status": "error"}


# --- helpers --------------------------------------------------------------------------------------

def _session(user):
    return SimpleNamespace(user=user, access_token=str(user.id))


class _FixedClock:
    """Replaces datetime in the route module so the cutoff is computed from NOW."""

    @staticmethod
    def now(tz=None):
        return NOW

    @staticmethod
    def fromisoformat(value):
        return datetime.fromisoformat(value)


def _no_ai():
    from fastapi import HTTPException

    raise HTTPException(503, "AI service is not configured")
