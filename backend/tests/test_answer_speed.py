"""Answer path: duplicate copies of a page are not repeated, answers are capped in length,
and the question is saved before its reply. No network calls."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ai.gemini_client import ANSWER_MAX_OUTPUT_TOKENS, GeminiClient
from app.ai.rag import select_evidence
from app.services.chat import ask_question
from tests.fakes import FakeAI, FakeDataClient

DOC_A, DOC_B = str(uuid4()), str(uuid4())


def _row(doc, title, page, text, similarity):
    return {"chunk_id": str(uuid4()), "document_id": doc, "title": title, "page_number": page,
            "content": text, "similarity": similarity}


def test_a_copy_of_the_same_page_is_not_repeated():
    rows = [
        _row(DOC_A, "PollToll", 1, "Verified input and change ledger.", 0.73),
        _row(DOC_B, "PollToll copy", 1, "Verified input and change ledger.", 0.73),
        _row(DOC_A, "PollToll", 4, "Explained flags and receipts.", 0.70),
    ]
    evidence = select_evidence(rows, min_similarity=0.3, limit=5)
    assert [(e.title, e.page_number) for e in evidence] == [("PollToll", 1), ("PollToll", 4)]


def test_the_same_boilerplate_on_different_pages_is_kept():
    rows = [_row(DOC_A, "Policy", page, "Confidential. Internal use.", 0.6) for page in (1, 2, 3)]
    assert len(select_evidence(rows, min_similarity=0.3, limit=5)) == 3


class _Models:
    def __init__(self):
        self.calls = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text="Answer [1].", usage_metadata=None)


@pytest.mark.asyncio
async def test_answers_are_capped_in_length():
    models = _Models()
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    gemini = GeminiClient("unused", "emb", "chat", client=client)
    await gemini.complete_with_usage("system", "question")
    config = models.calls[0]["config"]
    assert config.max_output_tokens == ANSWER_MAX_OUTPUT_TOKENS
    assert ANSWER_MAX_OUTPUT_TOKENS <= 512


@pytest.mark.asyncio
async def test_question_is_saved_before_the_reply_and_timings_are_logged(caplog):
    sb = FakeDataClient()
    student = uuid4()
    sb.rpc_responses["match_document_chunks"] = [
        _row(DOC_A, "Fee Policy", 2, "Hostel fees are waived for the LOA semester.", 0.8),
    ]
    from tests.conftest import make_profile
    user = make_profile(str(student), role="student", campus_id=str(uuid4()))
    ai = FakeAI(reply="Hostel fees are waived [1].")

    with caplog.at_level("INFO", logger="unibuddy.chat"):
        result = await ask_question(sb=sb, ai=ai, user=user, access_token=str(student),
                                    question="Are hostel fees waived?", conversation_id=None,
                                    top_k=5, min_similarity=0.3)

    roles = [row["role"] for row in sb.tables["messages"]]
    assert roles == ["user", "assistant"]
    assert result.answer.abstained is False
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("answer:"))
    assert "total_ms=" in line and "embed_ms=" in line and "match_ms=" in line and "answer_ms=" in line
    assert "Are hostel fees waived" not in line and "waived" not in line
