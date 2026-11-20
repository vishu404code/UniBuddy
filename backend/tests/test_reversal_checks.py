"""Reversal checks: an answer must not flip the meaning of its sources.

The sentence check is a refusal heuristic, not proof of correctness. These tests show two things:
1. Logical operators (order in time, comparison, obligation, scope, negation) are refused when the cited text does
   not use them, so reversals of those kinds are caught.
2. Word overlap alone would have passed some reversals, so overlap is not treated as evidence of correctness.

Fixtures only. The model is a fake with scripted replies."""

import pytest

from app.ai.rag import Evidence, _content_words, answer_question, claims_are_supported
from tests.fakes import FakeAI
from uuid import uuid4

SOURCE = "A late fee of 500 applies after 15 September. Students may pay the fee by card."


def _evidence(text=SOURCE):
    return [Evidence(chunk_id=uuid4(), document_id=uuid4(), title="FIXTURE Fee Policy", page_number=3,
                     content=text, similarity=0.9)]


@pytest.mark.parametrize("reply", [
    "The late fee applies before 15 September [1].",              # time order reversed
    "All students must pay the fee by card [1].",                 # scope and obligation strengthened
    "The late fee applies only to international students [1].",  # scope narrowed
    "The late fee does not apply after 15 September [1].",        # negation added
    "The fee costs less than 500 [1].",                           # comparison reversed
])
def test_a_reversed_or_strengthened_claim_is_refused(reply):
    assert not claims_are_supported(reply, SOURCE)


def test_a_claim_that_uses_the_same_operator_as_the_source_is_accepted():
    assert claims_are_supported("A late fee applies after 15 September [1].", SOURCE)
    assert claims_are_supported("Students may pay the fee by card [1].", SOURCE)


@pytest.mark.asyncio
async def test_a_reversal_is_refused_through_the_answer_path():
    answer = await answer_question("Is the late fee charged before 15 September?", _evidence(),
                                   FakeAI(reply="- The late fee applies before 15 September [1]."))

    assert answer.abstained is True
    assert answer.citations == []


def test_overlap_alone_would_pass_a_reversal_so_it_is_not_treated_as_proof():
    reply = "The late fee applies before 15 September"
    source_words = _content_words(SOURCE)
    reply_words = _content_words(reply)
    overlap = len(reply_words & source_words) / len(reply_words)

    assert overlap >= 0.6  # the word-overlap heuristic alone would accept this reversal
    assert not claims_are_supported(reply + " [1].", SOURCE)  # the operator check is what refuses it
