"""AI usage metering for summaries and embeddings, and the background chat tidy-up.

Synthetic fixtures and in-memory fakes only. No network calls.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.ai.gemini_client import GenerationUsage
from app.schemas.auth import CurrentUser
from app.services import chat_retention
from app.services.ai_usage import record_usage
from app.services.chat import ask_question
from app.services.errors import DataServiceError
from tests.fakes import FakeAI, FakeDataClient, add_ready_document

CAMPUS = uuid4()
OLD = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
RECENT = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
USAGE_FIELDS = {"id", "operation", "model", "request_count", "input_tokens", "output_tokens"}


def _student():
    return CurrentUser(id=uuid4(), email="s@example.com", full_name="S", role="student",
                       campus_id=CAMPUS, department_id=None)


def _conversation(sb, user_id):
    cid = uuid4()
    sb.tables["conversations"].append({"id": str(cid), "user_id": str(user_id), "title": "t", "created_at": OLD})
    return cid


def _message(sb, cid, role, content, created_at):
    mid = uuid4()
    sb.tables["messages"].append({"id": str(mid), "conversation_id": str(cid), "role": role,
                                  "content": content, "created_at": created_at})
    return mid


class UsageAI(FakeAI):
    """A scripted model that also reports usage, as the Gemini client does."""

    async def complete_with_usage(self, system, user):
        text = await self.complete(system, user)
        return text, GenerationUsage(model="gemini-test", input_tokens=11, output_tokens=7)


class FailingSummaryStore(FakeDataClient):
    async def insert_service(self, table, rows):
        if table == "chat_summaries":
            raise DataServiceError(503, "database unavailable")
        return await super().insert_service(table, rows)


@pytest.mark.asyncio
async def test_record_usage_writes_one_row_and_refuses_unknown_operations():
    sb = FakeDataClient()
    await record_usage(sb, operation="summary", model="m", input_tokens=3, output_tokens=2)

    row = sb.tables["ai_usage_events"][0]
    assert set(row) - {"created_at"} == USAGE_FIELDS  # created_at is the table default
    assert (row["operation"], row["model"], row["input_tokens"]) == ("summary", "m", 3)
    with pytest.raises(ValueError):
        await record_usage(sb, operation="student question text", model="m")


@pytest.mark.asyncio
async def test_a_failed_usage_write_never_fails_the_caller():
    sb = FailingSummaryStore()
    sb.tables["ai_usage_events"] = []

    async def broken(table, rows):
        raise DataServiceError(503, "database unavailable")

    sb.insert_service = broken
    await record_usage(sb, operation="answer", model="m")  # must not raise


@pytest.mark.asyncio
async def test_summary_call_is_metered_as_summary_with_the_returned_usage():
    sb = FakeDataClient()
    student = _student()
    cid = _conversation(sb, student.id)
    _message(sb, cid, "user", "When is the fee due?", OLD)
    _message(sb, cid, "assistant", "Week two.", OLD)

    await chat_retention.tidy_next_student_batch(sb=sb, ai=UsageAI(reply="Student asked about fees."))

    summaries = [r for r in sb.tables["ai_usage_events"] if r["operation"] == "summary"]
    assert len(summaries) == 1
    assert (summaries[0]["model"], summaries[0]["input_tokens"], summaries[0]["output_tokens"]) == ("gemini-test", 11, 7)


@pytest.mark.asyncio
async def test_background_tidy_saves_the_summary_before_removing_old_messages_and_keeps_recent_ones():
    sb = FakeDataClient()
    student = _student()
    cid = _conversation(sb, student.id)
    old_a = _message(sb, cid, "user", "Fee question", OLD)
    old_b = _message(sb, cid, "assistant", "Week two.", OLD)
    recent = _message(sb, cid, "user", "Hello again", RECENT)

    result = await chat_retention.tidy_next_student_batch(sb=sb, ai=FakeAI(reply="Fees were discussed."))

    assert result["status"] == "summarized"
    assert len(sb.tables["chat_summaries"]) == 1
    remaining = {m["id"] for m in sb.tables["messages"]}
    assert str(old_a) not in remaining and str(old_b) not in remaining
    assert str(recent) in remaining


@pytest.mark.asyncio
async def test_a_failed_summary_save_removes_no_messages():
    sb = FailingSummaryStore()
    student = _student()
    cid = _conversation(sb, student.id)
    _message(sb, cid, "user", "Fee question", OLD)

    with pytest.raises(DataServiceError):
        await chat_retention.tidy_next_student_batch(sb=sb, ai=FakeAI(reply="Summary."))

    assert len(sb.tables["messages"]) == 1


@pytest.mark.asyncio
async def test_a_student_whose_old_messages_are_all_ticket_linked_does_not_block_another_student():
    sb = FakeDataClient()
    blocked, other = _student(), _student()
    cid_blocked = _conversation(sb, blocked.id)
    linked = _message(sb, cid_blocked, "user", "Forwarded question", OLD)
    sb.tables["tickets"].append({"id": str(uuid4()), "source_message_id": str(linked)})
    cid_other = _conversation(sb, other.id)
    free = _message(sb, cid_other, "user", "Another question", OLD)

    result = await chat_retention.tidy_next_student_batch(sb=sb, ai=FakeAI(reply="Summary."))

    assert result["status"] == "summarized"
    remaining = {m["id"] for m in sb.tables["messages"]}
    assert str(free) not in remaining
    assert str(linked) in remaining  # a ticket points at it, so it is kept


@pytest.mark.asyncio
async def test_a_question_records_its_embedding_as_a_query_embedding_with_no_text():
    sb = FakeDataClient()
    add_ready_document(sb)
    sb.rpc_rows = []
    await ask_question(sb=sb, ai=FakeAI(), user=_student(), access_token="student-token",
                       question="When is the fee due?", conversation_id=None, top_k=5, min_similarity=0.3)

    rows = [r for r in sb.tables["ai_usage_events"] if r["operation"] == "query_embedding"]
    assert len(rows) == 1
    assert set(rows[0]) - {"created_at"} == USAGE_FIELDS
    assert rows[0]["request_count"] == 1
    assert "fee" not in str(rows[0]).lower()
