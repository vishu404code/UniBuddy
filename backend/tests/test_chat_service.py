from uuid import uuid4

import pytest

from app.ai.rag import ABSTAIN_MESSAGE
from app.schemas.auth import CurrentUser
from app.services.chat import ask_question, forward_message_to_faculty
from app.services.documents import DocumentConflict, DocumentError, DocumentNotFound
from tests.fakes import FakeAI, FakeDataClient

CAMPUS = uuid4()
DEPT = uuid4()
DOC = uuid4()


def _student(campus=CAMPUS):
    return CurrentUser(id=uuid4(), email="s@example.com", full_name="S", role="student",
                       campus_id=campus, department_id=None)


def _row(similarity, page=3):
    return {"chunk_id": str(uuid4()), "document_id": str(DOC), "title": "Fee Policy",
            "page_number": page, "content": "Pay in week two.", "similarity": similarity}


async def _ask(sb, ai, student, question="When is the fee due?", conversation_id=None):
    return await ask_question(
        sb=sb, ai=ai, user=student, access_token="student-token", question=question,
        conversation_id=conversation_id, top_k=5, min_similarity=0.3,
    )


@pytest.mark.asyncio
async def test_grounded_answer_is_saved_with_citations_and_retrieval_runs_as_the_user():
    sb = FakeDataClient()
    sb.rpc_rows = [_row(0.8)]
    ai = FakeAI(reply="Pay in week two [1].")
    student = _student()

    result = await _ask(sb, ai, student)

    assert result.answer.abstained is False
    assert result.answer.citations[0].page == 3
    assert sb.rpc_calls[0][0] == "student-token"
    assert sb.rpc_calls[0][1] == "match_document_chunks"
    roles = [m["role"] for m in sb.tables["messages"]]
    assert roles == ["user", "assistant"]
    assert sb.tables["messages"][1]["citations"][0]["title"] == "Fee Policy"
    assert sb.tables["conversations"][0]["user_id"] == str(student.id)


@pytest.mark.asyncio
async def test_weak_retrieval_abstains_and_does_not_call_the_model():
    sb = FakeDataClient()
    sb.rpc_rows = [_row(0.1)]
    ai = FakeAI(reply="should not be used")

    result = await _ask(sb, ai, _student())

    assert result.answer.abstained is True
    assert result.answer.text == ABSTAIN_MESSAGE
    assert ai.completions == []
    assert sb.tables["messages"][1]["citations"] == []


@pytest.mark.asyncio
async def test_empty_question_is_rejected():
    with pytest.raises(DocumentError):
        await _ask(FakeDataClient(), FakeAI(), _student(), question="   ")


@pytest.mark.asyncio
async def test_student_cannot_continue_someone_elses_conversation():
    sb = FakeDataClient()
    owner = _student()
    conversation_id = uuid4()
    sb.tables["conversations"].append({"id": str(conversation_id), "user_id": str(owner.id), "title": "x"})

    with pytest.raises(DocumentNotFound):
        await _ask(sb, FakeAI(), _student(), conversation_id=conversation_id)
    assert all(m.get("conversation_id") != str(conversation_id) for m in sb.tables["messages"])


@pytest.mark.asyncio
async def test_forward_creates_a_submitted_ticket_for_the_students_campus():
    sb = FakeDataClient()
    student = _student()
    conversation_id, message_id = uuid4(), uuid4()
    sb.tables["conversations"].append({"id": str(conversation_id), "user_id": str(student.id), "title": "t"})
    sb.tables["messages"].append({"id": str(message_id), "conversation_id": str(conversation_id),
                                  "role": "user", "content": "Is there a hostel curfew?"})
    sb.tables["departments"].append({"id": str(DEPT), "campus_id": str(CAMPUS), "name": "Hostel"})

    ticket = await forward_message_to_faculty(
        sb=sb, user=student, message_id=message_id, department_id=DEPT, priority="high", description="urgent",
    )

    created = sb.tables["tickets"][0]
    assert created["campus_id"] == str(CAMPUS)
    assert created["department_id"] == str(DEPT)
    assert created["status"] == "submitted"
    assert created["priority"] == "high"
    assert created["source_message_id"] == str(message_id)
    assert created["question"] == "Is there a hostel curfew?"
    assert ticket["ticket_number"] == created["ticket_number"]
    assert sb.tables["notifications"][0]["user_id"] == str(student.id)


@pytest.mark.asyncio
async def test_forwarding_the_same_question_twice_is_a_conflict():
    sb = FakeDataClient()
    student = _student()
    conversation_id, message_id = uuid4(), uuid4()
    sb.tables["conversations"].append({"id": str(conversation_id), "user_id": str(student.id), "title": "t"})
    sb.tables["messages"].append({"id": str(message_id), "conversation_id": str(conversation_id),
                                  "role": "user", "content": "q"})
    sb.tables["departments"].append({"id": str(DEPT), "campus_id": str(CAMPUS), "name": "Hostel"})
    await forward_message_to_faculty(sb=sb, user=student, message_id=message_id, department_id=DEPT,
                                     priority="medium", description=None)

    with pytest.raises(DocumentConflict):
        await forward_message_to_faculty(sb=sb, user=student, message_id=message_id, department_id=DEPT,
                                         priority="medium", description=None)


@pytest.mark.asyncio
async def test_forward_rejects_department_outside_students_campus():
    sb = FakeDataClient()
    student = _student()
    conversation_id, message_id = uuid4(), uuid4()
    sb.tables["conversations"].append({"id": str(conversation_id), "user_id": str(student.id), "title": "t"})
    sb.tables["messages"].append({"id": str(message_id), "conversation_id": str(conversation_id),
                                  "role": "user", "content": "q"})
    sb.tables["departments"].append({"id": str(DEPT), "campus_id": str(uuid4()), "name": "Elsewhere"})

    with pytest.raises(DocumentError, match="does not belong"):
        await forward_message_to_faculty(sb=sb, user=student, message_id=message_id, department_id=DEPT,
                                         priority="medium", description=None)


@pytest.mark.asyncio
async def test_forward_rejects_assistant_messages():
    sb = FakeDataClient()
    student = _student()
    conversation_id, message_id = uuid4(), uuid4()
    sb.tables["conversations"].append({"id": str(conversation_id), "user_id": str(student.id), "title": "t"})
    sb.tables["messages"].append({"id": str(message_id), "conversation_id": str(conversation_id),
                                  "role": "assistant", "content": "a"})

    with pytest.raises(DocumentError, match="Only a student question"):
        await forward_message_to_faculty(sb=sb, user=student, message_id=message_id, department_id=DEPT,
                                         priority="medium", description=None)
