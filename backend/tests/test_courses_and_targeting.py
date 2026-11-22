"""Courses, academic metadata on documents, targeted announcements and the student picker.
No network calls: the database is the in-memory fake. Row-level visibility of targeted announcements
is checked in tests/sql/courses_targeting_test.sql against the database itself."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.routes.people import find_students
from app.schemas.announcements import AnnouncementCreate
from app.services.announcements import create_announcement
from app.services.courses import create_course, list_courses, remove_course, update_course
from app.services.documents import (
    DocumentConflict,
    DocumentError,
    DocumentForbidden,
    clean_metadata,
    upload_document,
)
from tests.conftest import make_profile
from tests.fakes import FakeDataClient

PDF = b"%PDF-1.4\n% test document\n"
BUCKET = "test-documents"


def _campus(sb, name="Sonipat"):
    campus_id = str(uuid4())
    sb.tables["campuses"].append({"id": campus_id, "name": name, "code": f"{name.lower()}-{campus_id[:4]}"})
    return campus_id


def _authority(campus_id):
    return make_profile(str(uuid4()), role="authority", campus_id=campus_id)


def _faculty(campus_id):
    return make_profile(str(uuid4()), role="faculty", campus_id=campus_id)


def _student(sb, campus_id, *, name="Test Student", email=None, batch=None, course_id=None, section=None):
    student_id = str(uuid4())
    sb.tables["profiles"].append({
        "id": student_id, "email": email or f"{student_id[:8]}@example.edu", "full_name": name,
        "role": "student", "campus_id": campus_id, "department_id": None,
        "cross_campus_record_access": False, "academic_year": None, "batch_year": batch,
        "course_id": course_id, "section": section,
    })
    return make_profile(student_id, role="student", campus_id=campus_id)


def _options(sb, campus_id, *, years=("2026-27",), batches=("2026",), sections=("A", "B")):
    """Active filter options for a campus (test fixtures). Upload and announcement metadata must use them."""
    for kind, values in (("academic_year", years), ("batch", batches), ("section", sections)):
        for value in values:
            sb.tables["filter_options"].append({
                "id": str(uuid4()), "campus_id": campus_id, "kind": kind, "value": value, "active": True,
            })


async def _upload(sb, user, **overrides):
    metadata = overrides.get("metadata")
    targeted = bool(metadata and (metadata.academic_year or metadata.batch_year is not None or metadata.section
                                  or metadata.course_id is not None))
    options = dict(
        sb=sb, uploader=user, title="LOA policy", visibility="public_students", scope="campus",
        department_id=None, filename="loa.pdf", content_type="application/pdf", data=PDF,
        max_bytes=10_000_000, storage_bucket=BUCKET, audience="targeted" if targeted else "all_students",
    )
    options.update(overrides)
    return await upload_document(**options)


# --- Courses ----------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_authority_adds_a_course_and_faculty_sees_only_active_courses():
    sb = FakeDataClient()
    campus = _campus(sb)
    authority = _authority(campus)
    faculty = _faculty(campus)

    course = await create_course(sb, authority, "  BBA  ")
    assert course["name"] == "BBA"
    assert course["active"] is True

    await update_course(sb, authority, UUID(course["id"]), name=None, active=False)

    assert await list_courses(sb, faculty, include_inactive=False) == []
    shown = await list_courses(sb, authority, include_inactive=True)
    assert [row["name"] for row in shown] == ["BBA"]


@pytest.mark.asyncio
async def test_course_names_are_unique_per_campus_ignoring_case_but_can_repeat_across_campuses():
    sb = FakeDataClient()
    campus_1 = _campus(sb, "Sonipat")
    campus_2 = _campus(sb, "Other")
    await create_course(sb, _authority(campus_1), "BBA")

    with pytest.raises(DocumentConflict):
        await create_course(sb, _authority(campus_1), "bba")

    other = await create_course(sb, _authority(campus_2), "BBA")
    assert other["name"] == "BBA"


@pytest.mark.asyncio
async def test_only_authority_creates_renames_or_removes_courses():
    sb = FakeDataClient()
    campus = _campus(sb)
    course = await create_course(sb, _authority(campus), "CS")
    faculty = _faculty(campus)

    with pytest.raises(DocumentForbidden):
        await create_course(sb, faculty, "DSA")
    with pytest.raises(DocumentForbidden):
        await update_course(sb, faculty, UUID(course["id"]), name="CS & AI", active=None)
    with pytest.raises(DocumentForbidden):
        await remove_course(sb, faculty, UUID(course["id"]))
    assert [row["name"] for row in sb.tables["courses"]] == ["CS"]


@pytest.mark.asyncio
async def test_removing_an_unused_course_deletes_it():
    sb = FakeDataClient()
    campus = _campus(sb)
    authority = _authority(campus)
    course = await create_course(sb, authority, "DSA")

    result = await remove_course(sb, authority, UUID(course["id"]))

    assert result["action"] == "deleted"
    assert sb.tables["courses"] == []


@pytest.mark.asyncio
async def test_removing_a_course_in_use_deactivates_it_and_keeps_the_record():
    sb = FakeDataClient()
    campus = _campus(sb)
    _options(sb, campus)
    authority = _authority(campus)
    course = await create_course(sb, authority, "BBA")
    metadata = clean_metadata(academic_year="2026-27", batch_year=2026, section="A",
                              course_id=UUID(course["id"]), source_person=None)
    doc = await _upload(sb, authority, metadata=metadata)

    result = await remove_course(sb, authority, UUID(course["id"]))

    assert result["action"] == "deactivated"
    [row] = sb.tables["courses"]
    assert row["active"] is False
    assert str(sb.tables["documents"][0]["course_id"]) == course["id"]
    assert doc["id"] == sb.tables["documents"][0]["id"]


@pytest.mark.asyncio
async def test_course_names_are_trimmed_and_limited():
    sb = FakeDataClient()
    authority = _authority(_campus(sb))
    with pytest.raises(DocumentError):
        await create_course(sb, authority, "   ")
    with pytest.raises(DocumentError):
        await create_course(sb, authority, "x" * 81)


@pytest.mark.asyncio
async def test_renaming_to_an_existing_name_on_the_campus_is_refused():
    sb = FakeDataClient()
    campus = _campus(sb)
    authority = _authority(campus)
    await create_course(sb, authority, "BBA")
    second = await create_course(sb, authority, "CS")

    with pytest.raises(DocumentConflict):
        await update_course(sb, authority, UUID(second["id"]), name="bba", active=None)


# --- Documents: academic metadata -------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_stores_the_academic_metadata_with_the_document():
    sb = FakeDataClient()
    campus = _campus(sb)
    _options(sb, campus)
    authority = _authority(campus)
    course = await create_course(sb, authority, "CS & AI")
    faculty = _faculty(campus)
    metadata = clean_metadata(academic_year=" 2026-27 ", batch_year=2026, section="B",
                              course_id=UUID(course["id"]), source_person="  Dr Meera Rao  ")

    row = await _upload(sb, faculty, scope="university_wide", visibility="staff_only", metadata=metadata)

    stored = sb.tables["documents"][0]
    assert stored["academic_year"] == "2026-27"
    assert stored["batch_year"] == 2026
    assert stored["section"] == "B"
    assert str(stored["course_id"]) == course["id"]
    assert stored["source_person"] == "Dr Meera Rao"
    assert row["id"] == stored["id"]


@pytest.mark.asyncio
async def test_upload_refuses_a_course_from_another_campus():
    sb = FakeDataClient()
    campus_1 = _campus(sb, "Sonipat")
    campus_2 = _campus(sb, "Other")
    foreign = await create_course(sb, _authority(campus_2), "BBA")
    faculty = _faculty(campus_1)
    metadata = clean_metadata(academic_year=None, batch_year=None, section=None,
                              course_id=UUID(foreign["id"]), source_person=None)

    with pytest.raises(DocumentError):
        await _upload(sb, faculty, metadata=metadata)
    assert sb.tables["documents"] == []


@pytest.mark.asyncio
async def test_upload_refuses_an_inactive_course():
    sb = FakeDataClient()
    campus = _campus(sb)
    authority = _authority(campus)
    course = await create_course(sb, authority, "BBA")
    await update_course(sb, authority, UUID(course["id"]), name=None, active=False)
    metadata = clean_metadata(academic_year=None, batch_year=None, section=None,
                              course_id=UUID(course["id"]), source_person=None)

    with pytest.raises(DocumentError):
        await _upload(sb, _faculty(campus), metadata=metadata)


def test_metadata_limits_are_checked_and_blank_text_is_dropped():
    with pytest.raises(DocumentError):
        clean_metadata(academic_year=None, batch_year=1999, section=None, course_id=None, source_person=None)
    with pytest.raises(DocumentError):
        clean_metadata(academic_year=None, batch_year=None, section="ABCDEFGHIJK", course_id=None, source_person=None)

    meta = clean_metadata(academic_year="   ", batch_year=None, section=" ", course_id=None, source_person="")
    assert meta.academic_year is None
    assert meta.section is None
    assert meta.source_person is None


# --- Announcements: targeting -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_targeted_announcement_stores_its_filters_and_campus():
    sb = FakeDataClient()
    campus = _campus(sb)
    _options(sb, campus)
    authority = _authority(campus)
    course = await create_course(sb, authority, "BBA")
    body = AnnouncementCreate(title="Batch 2026 BBA", body="Orientation on Monday.",
                              batch_year=2026, course_id=UUID(course["id"]), section="A")

    row = await create_announcement(sb=sb, user=authority, body=body)

    assert row["batch_year"] == 2026
    assert str(row["course_id"]) == course["id"]
    assert row["section"] == "A"
    assert str(row["campus_id"]) == campus
    assert sb.tables["announcement_recipients"] == []


@pytest.mark.asyncio
async def test_selected_people_get_recipient_rows_and_must_be_students_on_the_campus():
    sb = FakeDataClient()
    campus = _campus(sb)
    _options(sb, campus)
    other_campus = _campus(sb, "Other")
    authority = _authority(campus)
    student = _student(sb, campus, name="Asha Rao")
    outsider = _student(sb, other_campus, name="Not Here")
    faculty_member = _faculty(campus)
    body = AnnouncementCreate(title="For you", body="Please see the office.", person_ids=[UUID(str(student.id))])

    await create_announcement(sb=sb, user=authority, body=body)
    recipients = sb.tables["announcement_recipients"]
    assert [str(r["profile_id"]) for r in recipients] == [str(student.id)]

    for bad in ([UUID(str(outsider.id))], [UUID(str(faculty_member.id))]):
        with pytest.raises(DocumentError):
            await create_announcement(sb=sb, user=authority, body=AnnouncementCreate(
                title="Bad", body="Nope.", person_ids=bad))
    assert len(sb.tables["announcements"]) == 1


@pytest.mark.asyncio
async def test_a_failed_recipient_write_removes_the_announcement_so_it_cannot_reach_everyone():
    sb = FakeDataClient()
    campus = _campus(sb)
    authority = _authority(campus)
    student = _student(sb, campus)
    original_insert = sb.insert_service

    async def fail_on_recipients(table, rows):
        if table == "announcement_recipients":
            raise RuntimeError("database unavailable")
        await original_insert(table, rows)

    sb.insert_service = fail_on_recipients
    body = AnnouncementCreate(title="Private", body="For one student.", person_ids=[UUID(str(student.id))])

    with pytest.raises(RuntimeError):
        await create_announcement(sb=sb, user=authority, body=body)
    assert sb.tables["announcements"] == []


@pytest.mark.asyncio
async def test_a_course_from_another_campus_is_refused_for_an_announcement():
    sb = FakeDataClient()
    campus = _campus(sb)
    other_campus = _campus(sb, "Other")
    foreign = await create_course(sb, _authority(other_campus), "BBA")
    faculty = _faculty(campus)

    with pytest.raises(DocumentError):
        await create_announcement(sb=sb, user=faculty, body=AnnouncementCreate(
            title="Hi", body="Hello.", course_id=UUID(foreign["id"])))
    assert sb.tables["announcements"] == []


def test_staff_only_announcements_cannot_carry_student_targets():
    with pytest.raises(ValidationError):
        AnnouncementCreate(title="Staff", body="Staff only.", audience="staff_only", batch_year=2026)


def test_targeting_fields_are_range_checked():
    with pytest.raises(ValidationError):
        AnnouncementCreate(title="x", body="y", batch_year=1900)
    with pytest.raises(ValidationError):
        AnnouncementCreate(title="x", body="y", person_ids=[uuid4() for _ in range(201)])


# --- Student picker ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_student_picker_returns_only_matching_students_on_the_callers_campus():
    sb = FakeDataClient()
    campus = _campus(sb)
    other_campus = _campus(sb, "Other")
    faculty = _faculty(campus)
    asha = _student(sb, campus, name="Asha Rao", email="asha@example.edu")
    _student(sb, campus, name="Ravi Kumar", email="ravi@example.edu")
    _student(sb, other_campus, name="Asha Other", email="asha.other@example.edu")
    sb.tables["profiles"].append({
        "id": str(uuid4()), "email": "asha.staff@example.edu", "full_name": "Asha Staff",
        "role": "faculty", "campus_id": campus, "department_id": None, "cross_campus_record_access": False,
    })
    session = SimpleNamespace(user=faculty, access_token=str(faculty.id))

    picks = await find_students(session=session, q="asha", sb=sb)

    assert [p.id for p in picks] == [str(asha.id)]
    assert picks[0].email == "asha@example.edu"


@pytest.mark.asyncio
async def test_student_picker_is_empty_for_a_user_without_a_campus():
    sb = FakeDataClient()
    _student(sb, _campus(sb))
    nobody = make_profile(str(uuid4()), role="faculty", campus_id=None)
    session = SimpleNamespace(user=nobody, access_token=str(nobody.id))

    assert await find_students(session=session, q="", sb=sb) == []


@pytest.mark.asyncio
async def test_metadata_must_use_an_active_option_of_the_campus():
    sb = FakeDataClient()
    campus = _campus(sb)
    _options(sb, campus, years=("2026-27",), sections=("A",))
    sb.tables["filter_options"][0]["active"] = False  # retire the academic year
    faculty = _faculty(campus)

    with pytest.raises(DocumentError):
        await _upload(sb, faculty, metadata=clean_metadata(academic_year="2026-27", batch_year=None,
                                                           section=None, course_id=None, source_person=None))
    with pytest.raises(DocumentError):
        await _upload(sb, faculty, metadata=clean_metadata(academic_year=None, batch_year=None,
                                                           section="Z", course_id=None, source_person=None))
    assert sb.tables["documents"] == []
