"""Student chat fast paths and bounds. Greetings, thanks and questions with no visible document never reach
the model. A stalled model call becomes the visible reply; an answer past the deadline is an error; a database
failure is never hidden. No network calls."""

import asyncio
from uuid import uuid4

import pytest

from app.schemas.auth import CurrentUser
from app.services import chat as chat_service
from app.services.chat import (
    GREETING_MESSAGE,
    NO_DOCUMENTS_MESSAGE,
    THANKS_MESSAGE,
    UNAVAILABLE_MESSAGE,
    AskTimedOut,
    ask_question,
)
from app.services.errors import DataServiceError
from tests.fakes import FakeAI, FakeDataClient, add_ready_document

CAMPUS = uuid4()


def _student():
    return CurrentUser(id=uuid4(), email="s@example.com", full_name="S", role="student",
                       campus_id=CAMPUS, department_id=None)


def _row(similarity=0.8):
    return {"chunk_id": str(uuid4()), "document_id": str(uuid4()), "title": "Fee Policy",
            "page_number": 3, "content": "Pay in week two.", "similarity": similarity}


async def _ask(sb, ai, question):
    return await ask_question(
        sb=sb, ai=ai, user=_student(), access_token="student-token", question=question,
        conversation_id=None, top_k=5, min_similarity=0.3,
    )


class RecordingAI(FakeAI):
    """Records every question embedding, so a test can prove the model was or was not called."""

    def __init__(self, reply=""):
        super().__init__(reply)
        self.queries: list[str] = []

    async def embed_query(self, text):
        self.queries.append(text)
        return await super().embed_query(text)


class HangingEmbeddingAI(FakeAI):
    async def embed_query(self, text):
        await asyncio.sleep(3600)


class HangingAnswerAI(FakeAI):
    async def complete(self, system, user):
        await asyncio.sleep(3600)


@pytest.mark.asyncio
@pytest.mark.parametrize("question", ["hello", "Hi!", "good morning", "Hey there"])
async def test_greetings_are_answered_without_search_or_model(question):
    sb = FakeDataClient()
    ai = RecordingAI(reply="should not be used")

    result = await _ask(sb, ai, question)

    assert result.answer.text == GREETING_MESSAGE
    assert result.answer.abstained is False
    assert result.answer.citations == []
    assert ai.queries == [] and ai.completions == []
    assert sb.rpc_calls == []
    assert [m["role"] for m in sb.tables["messages"]] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_thanks_are_answered_without_search_or_model():
    sb = FakeDataClient()
    ai = RecordingAI(reply="should not be used")

    result = await _ask(sb, ai, "Thank you!")

    assert result.answer.text == THANKS_MESSAGE
    assert ai.queries == [] and ai.completions == [] and sb.rpc_calls == []


@pytest.mark.asyncio
async def test_a_greeting_inside_a_real_question_is_still_searched():
    sb = FakeDataClient()
    add_ready_document(sb)
    sb.rpc_rows = [_row(0.8)]
    ai = RecordingAI(reply="Pay in week two [1].")

    result = await _ask(sb, ai, "hi, when is the fee due for the semester")

    assert ai.queries, "a real question must still be embedded"
    assert sb.rpc_calls, "a real question must still be searched"
    assert result.answer.abstained is False


@pytest.mark.asyncio
async def test_no_visible_document_replies_at_once_without_embedding_or_model():
    sb = FakeDataClient()
    ai = RecordingAI(reply="should not be used")

    result = await _ask(sb, ai, "When is the fee due?")

    assert result.answer.text == NO_DOCUMENTS_MESSAGE
    assert result.answer.abstained is True
    assert result.answer.citations == []
    assert ai.queries == [] and ai.completions == [] and sb.rpc_calls == []
    assert [m["role"] for m in sb.tables["messages"]] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_draft_documents_do_not_count_as_visible():
    sb = FakeDataClient()
    sb.tables["documents"].append({"id": str(uuid4()), "publication_status": "draft", "processing_status": "ready"})

    result = await _ask(sb, FakeAI(), "When is the fee due?")

    assert result.answer.text == NO_DOCUMENTS_MESSAGE


@pytest.mark.asyncio
async def test_documents_still_processing_do_not_count_as_visible():
    sb = FakeDataClient()
    sb.tables["documents"].append({"id": str(uuid4()), "publication_status": "published",
                                   "processing_status": "processing"})

    result = await _ask(sb, FakeAI(), "When is the fee due?")

    assert result.answer.text == NO_DOCUMENTS_MESSAGE


@pytest.mark.asyncio
async def test_a_stalled_embedding_becomes_the_visible_reply(monkeypatch):
    monkeypatch.setattr(chat_service, "MODEL_CALL_TIMEOUT_SECONDS", 0.05)
    sb = FakeDataClient()
    add_ready_document(sb)

    result = await _ask(sb, HangingEmbeddingAI(), "When is the fee due?")

    assert result.answer.text == UNAVAILABLE_MESSAGE
    assert result.answer.abstained is True
    assert result.answer.citations == []
    assert [m["role"] for m in sb.tables["messages"]] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_a_stalled_answer_becomes_the_visible_reply(monkeypatch):
    monkeypatch.setattr(chat_service, "MODEL_CALL_TIMEOUT_SECONDS", 0.05)
    sb = FakeDataClient()
    add_ready_document(sb)
    sb.rpc_rows = [_row(0.8)]

    result = await _ask(sb, HangingAnswerAI(), "When is the fee due?")

    assert result.answer.text == UNAVAILABLE_MESSAGE
    assert result.answer.citations == []


@pytest.mark.asyncio
async def test_an_answer_past_the_deadline_is_reported_as_an_error(monkeypatch):
    monkeypatch.setattr(chat_service, "ASK_DEADLINE_SECONDS", 0.05)
    sb = FakeDataClient()
    add_ready_document(sb)

    with pytest.raises(AskTimedOut):
        await _ask(sb, HangingEmbeddingAI(), "When is the fee due?")


@pytest.mark.asyncio
async def test_a_database_failure_is_not_hidden_as_an_answer():
    sb = FakeDataClient()
    add_ready_document(sb)

    async def database_down(*args, **kwargs):
        raise DataServiceError(503, "database unavailable")

    sb.rpc_as_user = database_down

    with pytest.raises(DataServiceError) as caught:
        await _ask(sb, FakeAI(reply="Pay in week two [1]."), "When is the fee due?")
    assert caught.value.status_code == 503
