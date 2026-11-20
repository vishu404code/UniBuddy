"""Every answer must be supported by the sources it cites. The checks are structural: they compare words and
numbers, and use no list of topics, so an unlisted or indirect question gets the same protection.

Fixtures only. Replies are scripted."""

import pytest

from app.ai.rag import Evidence, answer_question, claims_are_supported, numbers_are_grounded
from tests.fakes import FakeAI
from uuid import uuid4

SOURCE = "Autumn tuition is due by 1 September. A late fee of 500 applies after 15 September."


def _evidence(text=SOURCE, title="FIXTURE Fee Policy"):
    return [Evidence(chunk_id=uuid4(), document_id=uuid4(), title=title, page_number=3, content=text, similarity=0.9)]


# --- Numbers, dates and weekdays --------------------------------------------------------------------------

def test_a_number_the_cited_text_states_is_grounded():
    assert numbers_are_grounded("Tuition is due by 1 September [1].", SOURCE)


def test_a_number_the_cited_text_does_not_state_is_not_grounded():
    assert not numbers_are_grounded("Tuition is due on 15 July [1].", SOURCE)


def test_citation_markers_are_not_counted_as_numbers():
    assert numbers_are_grounded("Tuition is due by 1 September [1][2].", SOURCE)


def test_thousands_separators_are_read_as_the_same_number():
    assert numbers_are_grounded("The fee is 1,000 [1].", "The fee is 1000 for the term.")


def test_a_weekday_or_month_is_checked_by_its_name():
    assert not numbers_are_grounded("The office is closed on Monday [1].", "The office opens at nine.")


# --- Sentences ---------------------------------------------------------------------------------------------

def test_a_sentence_mostly_made_of_the_sources_words_is_supported():
    assert claims_are_supported("Autumn tuition is due by 1 September [1].", SOURCE)


def test_a_sentence_with_most_words_missing_from_the_sources_is_not_supported():
    assert not claims_are_supported("The library closes early on holidays [1].", SOURCE)


def test_one_unsupported_sentence_among_supported_ones_refuses_the_whole_answer():
    answer = "- Autumn tuition is due by 1 September [1].\n- The waiver applies to every student [1]."
    assert not claims_are_supported(answer, SOURCE)


def test_a_negation_the_sources_do_not_state_is_refused_even_when_every_other_word_matches():
    """Every content word of this reply is in the source, but the reply reverses the rule. Only the negation
    check can refuse it."""
    assert not claims_are_supported("The late fee does not apply after 15 September [1].", SOURCE)
    assert not claims_are_supported("A late fee of 500 never applies after 15 September [1].", SOURCE)


def test_a_negation_the_sources_also_state_is_accepted():
    source = "A late fee does not apply to students who pay before 15 September."
    assert claims_are_supported("The late fee does not apply before 15 September [1].", source)


@pytest.mark.asyncio
async def test_a_reversed_rule_is_refused_through_the_answer_path():
    answer = await answer_question("Is there a late fee after 15 September?", _evidence(),
                                   FakeAI(reply="- The late fee does not apply after 15 September [1]."))

    assert answer.abstained is True


def test_a_short_answer_with_no_content_words_has_nothing_to_check():
    assert claims_are_supported("Yes [1].", SOURCE)


def test_the_threshold_is_applied_to_content_words_not_to_function_words():
    source = "The library opens early on weekdays."
    # Six content words (library, opens, early, weekdays, closes, late); four appear in the source: 67%, supported.
    assert claims_are_supported("The library opens early on weekdays and closes late [1].", source)
    # Four content words (library, closes, early, holidays); two appear in the source: 50%, below 60%, not supported.
    assert not claims_are_supported("Library closes early for holidays [1].", source)


# --- Through the answer path, for unlisted topics -----------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [
    "- Holiday closures apply to all staff [1].",          # no listed keyword, claim not in the source
    "- Hostel rooms are allocated by lottery [1].",         # unlisted topic, claim not in the source
    "- The waiver applies to every student [1].",           # indirect wording, claim not in the source
])
async def test_unsupported_claims_on_unlisted_topics_abstain(reply):
    answer = await answer_question("Can I get a waiver?", _evidence("Autumn tuition is due by 1 September."),
                                   FakeAI(reply=reply))

    assert answer.abstained is True
    assert answer.citations == []


@pytest.mark.asyncio
async def test_a_supported_answer_on_an_unlisted_topic_passes_with_its_citation():
    source = "Hostel rooms are allocated by lottery in the first week of term."
    answer = await answer_question("How are hostel rooms given out?", _evidence(source, "FIXTURE Hostel Rules"),
                                   FakeAI(reply="- Hostel rooms are allocated by lottery [1]."))

    assert answer.abstained is False
    assert [c.title for c in answer.citations] == ["FIXTURE Hostel Rules"]


@pytest.mark.asyncio
async def test_no_evidence_abstains_without_asking_the_model():
    ai = FakeAI(reply="- Autumn tuition is due by 1 September [1].")

    answer = await answer_question("When is tuition due?", [], ai)

    assert answer.abstained is True
    assert ai.completions == []


@pytest.mark.asyncio
async def test_a_wrong_date_with_otherwise_supported_words_is_refused_by_the_number_check():
    """The words all appear in the source, so only the number check can refuse this reply."""
    answer = await answer_question("When is tuition due?", _evidence(),
                                   FakeAI(reply="- Autumn tuition is due by 2 September [1]."))

    assert answer.abstained is True


@pytest.mark.asyncio
async def test_a_reply_that_cites_a_source_number_that_does_not_exist_abstains():
    answer = await answer_question("When is tuition due?", _evidence(), FakeAI(reply="- Tuition is due [9]."))

    assert answer.abstained is True
