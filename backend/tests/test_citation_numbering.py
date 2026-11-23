"""Citation markers in an answer point at the citations the student sees, not at the retrieved-source list."""
import asyncio
from uuid import uuid4

from app.ai.rag import Evidence, answer_question


class Fixed:
    def __init__(self, text):
        self.text = text

    async def complete(self, system, user):
        return self.text


def _ev(doc, page, text):
    return Evidence(chunk_id=uuid4(), document_id=doc, title=f"Doc {page}", page_number=page, content=text, similarity=0.9)


def test_markers_follow_the_listed_citations_when_two_sources_share_a_page():
    doc = uuid4()
    evidence = [
        _ev(doc, 1, "The library opens at nine every weekday morning for students."),
        _ev(doc, 1, "The library closes at eight in the evening on weekdays for students."),  # same page, second chunk
        _ev(doc, 2, "Hostel fees are paid each semester through the student portal."),
    ]
    answer = asyncio.run(answer_question(
        "When is the library open and what do hostel fees cover?",
        evidence,
        Fixed("- The library opens at nine every weekday morning [1].\n- Hostel fees are paid each semester through the student portal [3]."),
    ))

    assert [c.page for c in answer.citations] == [1, 2]
    assert "[1]" in answer.text and "[2]" in answer.text and "[3]" not in answer.text


def test_a_marker_on_a_later_source_is_never_left_pointing_past_the_list():
    doc = uuid4()
    evidence = [_ev(doc, p, f"Notice number {p} says the examination timetable is published on the portal.") for p in (1, 2, 3)]
    answer = asyncio.run(answer_question(
        "Where is the examination timetable published?",
        evidence,
        Fixed("The examination timetable is published on the student portal [3]."),
    ))

    markers = [int(m) for m in __import__("re").findall(r"\[(\d+)\]", answer.text)]
    assert markers and max(markers) <= len(answer.citations)
