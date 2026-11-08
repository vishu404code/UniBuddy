"""Student chat edge cases: AI outages keep the question forwardable, and citation formats parse."""

from uuid import uuid4

import pytest

from app.ai.gemini_client import AIServiceError
from app.ai.rag import Evidence, answer_question
from app.schemas.auth import CurrentUser
from app.services.chat import UNAVAILABLE_MESSAGE, ask_question
from tests.fakes import FakeAI, FakeSupabase

CAMPUS = uuid4()
DOC = uuid4()


def _student():
    return CurrentUser(id=uuid4(), email="s@example.com", full_name="S", role="student",
                       campus_id=CAMPUS, department_id=None)


def _row(similarity, page):
    return {"chunk_id": str(uuid4()), "document_id": str(DOC), "title": "Leave Policy",
            "page_number": page, "content": "Leave is granted for one semester.", "similarity": similarity}


def _evidence(page):
    return Evidence(chunk_id=uuid4(), document_id=DOC, title="Leave Policy", page_number=page,
                    content="Leave is granted for one semester.", similarity=0.9)


class BrokenAI(FakeAI):
    """Simulates Gemini being unavailable (for example, quota exhausted)."""

    async def embed_query(self, text):
        raise AIServiceError("Gemini embedding returned HTTP 429")

    async def complete(self, system, user):
        raise AIServiceError("Gemini answer returned HTTP 429")


@pytest.mark.asyncio
async def test_ai_outage_saves_the_question_and_an_unavailable_reply_with_no_citations():
    sb = FakeSupabase()
    student = _student()

    result = await ask_question(
        sb=sb, ai=BrokenAI(), user=student, access_token="student-token",
        question="How long is leave?", conversation_id=None, top_k=5, min_similarity=0.3,
    )

    assert result.answer.abstained is True
    assert result.answer.citations == []
    assert result.answer.text == UNAVAILABLE_MESSAGE
    roles = [m["role"] for m in sb.tables["messages"]]
    assert roles == ["user", "assistant"]
    assert sb.tables["messages"][0]["content"] == "How long is leave?"
    assert sb.tables["messages"][1].get("citations") == []


@pytest.mark.asyncio
async def test_ai_outage_does_not_claim_an_answer_or_invent_a_source():
    sb = FakeSupabase()

    await ask_question(
        sb=sb, ai=BrokenAI(), user=_student(), access_token="student-token",
        question="How long is leave?", conversation_id=None, top_k=5, min_similarity=0.3,
    )

    assistant = sb.tables["messages"][1]
    assert "Source" not in assistant["content"]
    assert assistant["content"] == UNAVAILABLE_MESSAGE


@pytest.mark.asyncio
async def test_model_citing_several_sources_in_one_bracket_is_still_grounded():
    evidence = [_evidence(4), _evidence(5)]
    answer = await answer_question("How long is leave?", evidence, FakeAI(reply="One semester [1, 2]."))

    assert answer.abstained is False
    assert [c.page for c in answer.citations] == [4, 5]


@pytest.mark.asyncio
async def test_adjacent_bracket_citations_are_still_grounded():
    evidence = [_evidence(4), _evidence(5)]
    answer = await answer_question("How long is leave?", evidence, FakeAI(reply="One semester [1][2]."))

    assert answer.abstained is False
    assert len(answer.citations) == 2


@pytest.mark.asyncio
async def test_citation_numbers_outside_the_sources_are_ignored():
    evidence = [_evidence(4)]
    answer = await answer_question("How long is leave?", evidence, FakeAI(reply="Grounded [9]."))

    assert answer.abstained is True
    assert answer.citations == []
