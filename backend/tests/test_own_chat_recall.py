"""Explicit recall of the Student's own earlier chats.

Rules these tests hold:
1. Recall happens only when the Student asks for it (AskRequest.recall_own_chats) and the flag is on.
2. A recall reply is built from the Student's own saved summaries only: no document is searched, no question is
   embedded, and no model is called.
3. Another Student's summaries never appear.
4. A summary that carries a number, a date or a month is withheld, so recall cannot carry a college fact.
5. Without an explicit request, or with the flag off, chat history is not read at all.
6. The summariser is instructed never to record college facts the assistant stated.

Fixtures only. No model, no network."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.ai.rag import Evidence
from app.config import settings
from app.schemas.chat import AskRequest
from app.services.chat import ask_question
from app.services.chat_retention import SYSTEM_PROMPT
from tests.conftest import make_profile
from tests.fakes import FakeAI, FakeDataClient

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
SOURCE = "FIXTURE: Autumn tuition is due by 1 September."


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "chat_memory_context_enabled", True)


def _student(sb, name="Fixture Student"):
    student = make_profile(str(uuid4()), role="student", campus_id=str(uuid4()))
    sb.tables["profiles"].append({"id": str(student.id), "email": f"{student.id}@example.edu", "full_name": name,
                                  "role": "student", "campus_id": str(student.campus_id)})
    return student


def _db(with_document=True):
    sb = FakeDataClient(visible=lambda token, table, row: table != "chat_summaries" or row.get("user_id") == token)
    sb.rpc_rows = [{"chunk_id": str(uuid4()), "document_id": str(uuid4()), "title": "FIXTURE Fee Policy",
                    "page_number": 3, "content": SOURCE, "similarity": 0.8}] if with_document else []
    return sb


def _summary(sb, owner, text, days_ago=10):
    stamp = (NOW - timedelta(days=days_ago)).isoformat()
    sb.tables["chat_summaries"].append({
        "id": str(uuid4()), "user_id": str(owner.id), "conversation_id": None, "batch_key": uuid4().hex * 2,
        "message_count": 1, "first_message_at": stamp, "last_message_at": stamp, "created_at": stamp,
        "summary": text, "importance": "normal", "use_count": 0, "last_used_at": None, "corrected_at": None,
    })


def _track(sb):
    touched = []
    for name, pos in (("select_page_as_user", 1), ("select_as_user", 1), ("select_service", 0),
                      ("insert_service", 0), ("update_service", 0)):
        original = getattr(sb, name)

        def make(orig, p):
            async def wrapper(*args, **kwargs):
                touched.append(args[p])
                return await orig(*args, **kwargs)
            return wrapper

        setattr(sb, name, make(original, pos))
    return touched


async def _ask(sb, student, ai, question="What did I ask about last week?", recall=True, memory_enabled=True):
    return await ask_question(
        sb=sb, ai=ai, user=student, access_token=str(student.id), question=question, conversation_id=None,
        top_k=5, min_similarity=0.3, memory_enabled=memory_enabled, recall_own_chats=recall,
    )


# --- Recall answers from the Student's own summaries only ------------------------------------------------

@pytest.mark.asyncio
async def test_recall_is_built_from_the_students_own_summaries_with_no_document_and_no_model():
    sb = _db()
    student = _student(sb)
    _summary(sb, student, "Asked about the process for requesting a fee deferral.")
    ai = FakeAI(reply="THIS MUST NOT BE USED")

    result = await _ask(sb, student, ai)

    assert "Asked about the process for requesting a fee deferral." in result.answer.text
    assert "not official sources" in result.answer.text
    assert result.answer.citations == []
    assert result.answer.abstained is False
    assert ai.completions == []  # no model call
    assert ai.embedded == []  # no question embedded, so no retrieval


@pytest.mark.asyncio
async def test_recall_never_includes_another_students_summaries():
    sb = _db()
    alice, bob = _student(sb, "Alice"), _student(sb, "Bob")
    _summary(sb, alice, "Asked about library opening times.")
    _summary(sb, bob, "Asked about bus passes.")

    result = await _ask(sb, alice, FakeAI())

    assert "library opening times" in result.answer.text
    assert "bus passes" not in result.answer.text


@pytest.mark.asyncio
async def test_a_summary_with_a_number_a_date_or_a_month_is_withheld_from_recall():
    sb = _db()
    student = _student(sb)
    _summary(sb, student, "Asked whether the late fee is 500.")
    _summary(sb, student, "Asked about the deadline on 15 July.")
    _summary(sb, student, "Asked about hostel rooms in March.")
    _summary(sb, student, "Asked about the library opening times.")

    result = await _ask(sb, student, FakeAI())

    assert "library opening times" in result.answer.text
    assert "late fee" not in result.answer.text
    assert "15 July" not in result.answer.text
    assert "March" not in result.answer.text


@pytest.mark.asyncio
async def test_recall_with_nothing_to_show_says_so_and_does_not_guess():
    sb = _db()
    student = _student(sb)
    ai = FakeAI(reply="A guess")

    result = await _ask(sb, student, ai)

    assert result.answer.abstained is True
    assert result.answer.text.startswith("I couldn't find that in your earlier chats.")
    assert ai.completions == []


# --- Recall is explicit and flag-gated ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recall_is_ignored_when_the_flag_is_off_and_no_history_is_read():
    sb = _db()
    student = _student(sb)
    _summary(sb, student, "Asked about the library opening times.")
    touched = _track(sb)
    ai = FakeAI(reply="- Autumn tuition is due by 1 September [1].")

    result = await _ask(sb, student, ai, question="When is tuition due?", memory_enabled=False)

    assert "library opening times" not in result.answer.text
    assert "chat_summaries" not in touched
    assert "chat_answer_preferences" not in touched


@pytest.mark.asyncio
async def test_without_an_explicit_request_history_is_not_read_even_with_the_flag_on():
    sb = _db()
    student = _student(sb)
    _summary(sb, student, "Asked about the library opening times.")
    touched = _track(sb)
    ai = FakeAI(reply="- Autumn tuition is due by 1 September [1].")

    result = await _ask(sb, student, ai, question="When is tuition due?", recall=False)

    assert "library opening times" not in result.answer.text
    assert "chat_summaries" not in touched


def test_the_request_flag_defaults_to_off_and_can_be_set_explicitly():
    assert AskRequest(question="What did I ask?").recall_own_chats is False
    assert AskRequest(question="What did I ask?", recall_own_chats=True).recall_own_chats is True


# --- The summariser must not record college facts -------------------------------------------------------

def test_the_summariser_is_told_never_to_record_college_facts_the_assistant_stated():
    assert "Never record a college fact" in SYSTEM_PROMPT
    assert "assistant stated" in SYSTEM_PROMPT


def test_evidence_fields_used_by_the_answer_path_are_unchanged():
    assert {"chunk_id", "document_id", "title", "page_number", "content", "similarity"} <= set(
        Evidence.__dataclass_fields__)
