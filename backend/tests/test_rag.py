from uuid import uuid4

import pytest

from app.ai.rag import (
    ABSTAIN_MESSAGE,
    INSUFFICIENT_MARKER,
    answer_question,
    build_user_prompt,
    select_evidence,
)
from tests.fakes import FakeAI

DOC_A = str(uuid4())
DOC_B = str(uuid4())


def _row(doc_id, title, page, similarity, content="policy text"):
    return {
        "chunk_id": str(uuid4()),
        "document_id": doc_id,
        "title": title,
        "page_number": page,
        "content": content,
        "similarity": similarity,
    }


def test_select_evidence_drops_weak_matches_and_sorts_strongest_first():
    rows = [
        _row(DOC_A, "Fee Policy", 2, 0.41),
        _row(DOC_B, "Calendar", 1, 0.12),
        _row(DOC_A, "Fee Policy", 4, 0.66),
    ]

    evidence = select_evidence(rows, min_similarity=0.3, limit=5)

    assert [e.page_number for e in evidence] == [4, 2]


def test_select_evidence_respects_limit():
    rows = [_row(DOC_A, "Fee Policy", i, 0.9 - i * 0.01) for i in range(10)]

    assert len(select_evidence(rows, min_similarity=0.3, limit=3)) == 3


@pytest.mark.asyncio
async def test_no_evidence_abstains_without_calling_the_model():
    generator = FakeAI(reply="should not be used")

    answer = await answer_question("When is the fee deadline?", [], generator)

    assert answer.abstained is True
    assert answer.text == ABSTAIN_MESSAGE
    assert answer.citations == []
    assert generator.completions == []


@pytest.mark.asyncio
async def test_model_reporting_insufficient_evidence_abstains():
    evidence = select_evidence([_row(DOC_A, "Fee Policy", 3, 0.8)], min_similarity=0.3, limit=5)
    generator = FakeAI(reply=INSUFFICIENT_MARKER)

    answer = await answer_question("What is the hostel curfew?", evidence, generator)

    assert answer.abstained is True
    assert answer.citations == []


@pytest.mark.asyncio
async def test_answer_without_citation_markers_abstains():
    evidence = select_evidence([_row(DOC_A, "Fee Policy", 3, 0.8)], min_similarity=0.3, limit=5)
    generator = FakeAI(reply="The fee is due in week two.")

    answer = await answer_question("When is the fee due?", evidence, generator)

    assert answer.abstained is True


@pytest.mark.asyncio
async def test_citations_come_from_retrieved_metadata_only():
    evidence = select_evidence(
        [_row(DOC_A, "Fee Policy", 3, 0.8), _row(DOC_B, "Calendar", 1, 0.7)],
        min_similarity=0.3,
        limit=5,
    )
    generator = FakeAI(reply="Pay in week two [1]. The calendar lists exams [2] and [9].")

    answer = await answer_question("When is the fee due?", evidence, generator)

    assert answer.abstained is False
    assert [(c.title, c.page) for c in answer.citations] == [("Fee Policy", 3), ("Calendar", 1)]
    assert str(answer.citations[0].document_id) == DOC_A


@pytest.mark.asyncio
async def test_prompt_contains_numbered_sources_and_question():
    evidence = select_evidence([_row(DOC_A, "Fee Policy", 3, 0.8, content="Pay by week two.")], 0.3, 5)

    prompt = build_user_prompt("When?", evidence)

    assert "[1] Fee Policy, page 3" in prompt
    assert "Pay by week two." in prompt
    assert prompt.endswith("QUESTION: When?")
