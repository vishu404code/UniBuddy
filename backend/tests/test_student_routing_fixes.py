"""Student routing, optional ticket department, pre-authorized Management, campus assignment,
and Authority restore and scope changes. No network calls; the database is the in-memory fake."""

from uuid import UUID, uuid4

import pytest

from app.services.chat import forward_message_to_faculty
from app.services.documents import (
    DocumentConflict,
    DocumentError,
    DocumentForbidden,
    restore_document,
    set_document_scope,
)
from app.services.errors import DataServiceError
from app.services.google_sign_in import GoogleSignInError, sign_in
from tests.conftest import make_profile
from tests.fakes import FakeDataClient

CLIENT_ID = "routing-test.apps.googleusercontent.com"
SECRET = "r" * 40
TOKEN = "y" * 30
MANAGEMENT_EMAIL = "jaysinghf204@gmail.com"
FACULTY_EMAIL = "tarun.s26366@nst.rishihood.edu.in"
SONIPAT = "Rishihood University, Sonipat"


def _verifier(email, subject="sub-1", verified=True):
    def verify(token, client_id):
        assert client_id == CLIENT_ID
        return {"iss": "https://accounts.google.com", "sub": subject, "aud": CLIENT_ID,
                "email": email, "email_verified": verified, "name": "Test Person"}

    return verify


async def _sign_in(sb, email, subject="sub-1", verified=True):
    return await sign_in(sb=sb, id_token=TOKEN, client_id=CLIENT_ID, session_secret=SECRET,
                         verifier=_verifier(email, subject, verified))


def _sonipat(sb):
    campus_id = str(uuid4())
    sb.tables["campuses"] = [{"id": campus_id, "name": SONIPAT, "code": "sonipat"}]
    return campus_id


# --- Forward to Faculty: department is optional -------------------------------------------

def _question(sb, student_id, campus_id):
    conversation_id = str(uuid4())
    message_id = str(uuid4())
    sb.tables["conversations"].append({"id": conversation_id, "user_id": student_id, "title": "t"})
    sb.tables["messages"].append({"id": message_id, "conversation_id": conversation_id, "role": "user",
                                  "content": "What is the LOA policy?"})
    return UUID(message_id)


@pytest.mark.asyncio
async def test_forward_without_a_department_goes_to_the_campus_queue():
    sb = FakeDataClient()
    campus_id = _sonipat(sb)
    student = make_profile(str(uuid4()), role="student", campus_id=campus_id)
    message_id = _question(sb, str(student.id), campus_id)

    ticket = await forward_message_to_faculty(sb=sb, user=student, message_id=message_id,
                                              department_id=None, priority="medium", description=None)

    [row] = sb.tables["tickets"]
    assert row["department_id"] is None
    assert str(row["campus_id"]) == campus_id
    assert ticket["ticket_number"]


@pytest.mark.asyncio
async def test_forward_with_a_department_of_the_same_campus_still_works():
    sb = FakeDataClient()
    campus_id = _sonipat(sb)
    department_id = str(uuid4())
    sb.tables["departments"].append({"id": department_id, "campus_id": campus_id, "name": "ABC"})
    student = make_profile(str(uuid4()), role="student", campus_id=campus_id)
    message_id = _question(sb, str(student.id), campus_id)

    await forward_message_to_faculty(sb=sb, user=student, message_id=message_id,
                                     department_id=UUID(department_id), priority="high", description=None)

    assert str(sb.tables["tickets"][0]["department_id"]) == department_id


@pytest.mark.asyncio
async def test_forward_refuses_a_department_from_another_campus():
    sb = FakeDataClient()
    campus_id = _sonipat(sb)
    other_department = str(uuid4())
    sb.tables["departments"].append({"id": other_department, "campus_id": str(uuid4()), "name": "ABC"})
    student = make_profile(str(uuid4()), role="student", campus_id=campus_id)
    message_id = _question(sb, str(student.id), campus_id)

    with pytest.raises(DocumentError):
        await forward_message_to_faculty(sb=sb, user=student, message_id=message_id,
                                         department_id=UUID(other_department), priority="medium",
                                         description=None)
    assert sb.tables["tickets"] == []


# --- Pre-authorized Management, before any Student profile --------------------------------

@pytest.mark.asyncio
async def test_preauthorized_management_identity_gets_management_and_no_student_profile():
    sb = FakeDataClient()
    _sonipat(sb)

    await _sign_in(sb, MANAGEMENT_EMAIL, subject="google-jay")

    assert [row["role"] for row in sb.tables["profiles"]] == ["management"]
    assert sb.tables["profiles"][0]["campus_id"] is None
    assert sb.tables["profiles"][0]["department_id"] is None


@pytest.mark.asyncio
async def test_management_email_is_matched_case_insensitively_and_needs_a_verified_email():
    sb = FakeDataClient()
    with pytest.raises(GoogleSignInError):
        await _sign_in(sb, "JaySinghF204@Gmail.com", verified=False)
    assert sb.tables["profiles"] == []

    await _sign_in(sb, "JaySinghF204@Gmail.com", subject="google-jay")
    assert sb.tables["profiles"][0]["role"] == "management"


@pytest.mark.asyncio
async def test_other_accounts_are_never_promoted_to_management():
    sb = FakeDataClient()
    _sonipat(sb)
    await _sign_in(sb, "someone.else@example.com", subject="google-other")
    assert sb.tables["profiles"][0]["role"] == "student"


@pytest.mark.asyncio
async def test_faculty_preauthorization_is_unchanged():
    sb = FakeDataClient()
    _sonipat(sb)
    await _sign_in(sb, FACULTY_EMAIL, subject="google-tarun")
    assert sb.tables["profiles"][0]["role"] == "faculty"


# --- Campus assignment for Students ---------------------------------------------------------

@pytest.mark.asyncio
async def test_new_student_gets_the_only_campus_through_the_database_function():
    sb = FakeDataClient()
    campus_id = _sonipat(sb)
    await _sign_in(sb, "new.student@example.com", subject="google-new")
    assert str(sb.tables["profiles"][0]["campus_id"]) == campus_id


@pytest.mark.asyncio
async def test_campus_assignment_failure_does_not_block_sign_in():
    sb = FakeDataClient()
    _sonipat(sb)
    real_rpc = sb.rpc_service

    async def failing_assign(function, payload):
        if function == "assign_campus_to_student":
            raise DataServiceError(403, "not allowed")
        return await real_rpc(function, payload)

    sb.rpc_service = failing_assign
    session = await _sign_in(sb, "new.student@example.com", subject="google-new")
    assert session["access_token"]
    assert sb.tables["profiles"][0]["role"] == "student"
    assert sb.tables["profiles"][0]["campus_id"] is None


@pytest.mark.asyncio
async def test_existing_student_without_a_campus_is_given_it_on_next_sign_in():
    sb = FakeDataClient()
    campus_id = _sonipat(sb)
    account_id = str(uuid4())
    sb.tables["account_identities"].append({"id": account_id, "email": "old.student@example.com", "google_subject": "google-old"})
    sb.tables["profiles"].append({"id": account_id, "email": "old.student@example.com", "full_name": "Old",
                                  "role": "student", "campus_id": None, "department_id": None,
                                  "cross_campus_record_access": False})

    await _sign_in(sb, "old.student@example.com", subject="google-old")

    assert str(sb.tables["profiles"][0]["campus_id"]) == campus_id


# --- Authority: restore an archived draft and change scope --------------------------------

def _document(**overrides):
    row = {
        "id": str(uuid4()), "title": "Leave of absence policy 2026-27", "original_filename": "absense.pdf",
        "file_size_bytes": 500780, "uploaded_by": None, "campus_id": None, "scope": "campus",
        "visibility": "public_students", "processing_status": "ready", "publication_status": "archived",
    }
    row.update(overrides)
    return row


def _authority(campus_id):
    return make_profile(str(uuid4()), role="authority", campus_id=campus_id)


@pytest.mark.asyncio
async def test_authority_restores_an_archived_document_as_a_draft_without_a_new_file():
    sb = FakeDataClient()
    campus_id = _sonipat(sb)
    authority = _authority(campus_id)
    doc = _document(uploaded_by=str(authority.id), campus_id=campus_id)
    sb.tables["documents"].append(doc)

    restored = await restore_document(sb=sb, user=authority, access_token=str(authority.id), document_id=UUID(doc["id"]))

    assert restored["publication_status"] == "draft"
    assert len(sb.tables["documents"]) == 1


@pytest.mark.asyncio
async def test_restore_is_refused_when_the_same_file_is_already_active():
    sb = FakeDataClient()
    campus_id = _sonipat(sb)
    authority = _authority(campus_id)
    archived = _document(uploaded_by=str(authority.id), campus_id=campus_id)
    active = _document(uploaded_by=str(authority.id), campus_id=campus_id, publication_status="published",
                       title="Another copy")
    sb.tables["documents"].extend([archived, active])

    with pytest.raises(DocumentConflict):
        await restore_document(sb=sb, user=authority, access_token=str(authority.id), document_id=UUID(archived["id"]))


@pytest.mark.asyncio
async def test_restore_is_refused_for_a_document_that_is_not_archived():
    sb = FakeDataClient()
    campus_id = _sonipat(sb)
    authority = _authority(campus_id)
    doc = _document(uploaded_by=str(authority.id), campus_id=campus_id, publication_status="published")
    sb.tables["documents"].append(doc)

    with pytest.raises(DocumentConflict):
        await restore_document(sb=sb, user=authority, access_token=str(authority.id), document_id=UUID(doc["id"]))


@pytest.mark.asyncio
async def test_authority_makes_a_draft_university_wide_and_faculty_cannot():
    sb = FakeDataClient()
    campus_id = _sonipat(sb)
    authority = _authority(campus_id)
    doc = _document(uploaded_by=str(authority.id), campus_id=campus_id, publication_status="draft")
    sb.tables["documents"].append(doc)

    changed = await set_document_scope(sb=sb, user=authority, access_token=str(authority.id),
                                       document_id=UUID(doc["id"]), scope="university_wide")
    assert changed["scope"] == "university_wide"

    faculty = make_profile(str(uuid4()), role="faculty", campus_id=campus_id)
    doc2 = _document(uploaded_by=str(faculty.id), campus_id=campus_id, publication_status="draft", title="F")
    sb.tables["documents"].append(doc2)
    with pytest.raises(DocumentForbidden):
        await set_document_scope(sb=sb, user=faculty, access_token=str(faculty.id),
                                 document_id=UUID(doc2["id"]), scope="university_wide")


@pytest.mark.asyncio
async def test_scope_cannot_change_on_a_published_document():
    sb = FakeDataClient()
    campus_id = _sonipat(sb)
    authority = _authority(campus_id)
    doc = _document(uploaded_by=str(authority.id), campus_id=campus_id, publication_status="published")
    sb.tables["documents"].append(doc)

    with pytest.raises(DocumentConflict):
        await set_document_scope(sb=sb, user=authority, access_token=str(authority.id),
                                 document_id=UUID(doc["id"]), scope="university_wide")
