"""Document audience on every upload, and Authority-only assignment of student academic values.

Synthetic fixtures and the in-memory fake. Real student information is never used.
"""

from uuid import uuid4

import pytest

from app.schemas.auth import CurrentUser
from app.services.academics import assign_student_academics
from app.services.documents import AcademicMetadata, DocumentError, DocumentForbidden, DocumentNotFound, require_audience
from tests.fakes import FakeDataClient

CAMPUS = uuid4()
OTHER_CAMPUS = uuid4()


def _user(role, campus=CAMPUS):
    return CurrentUser(id=uuid4(), email=f"{role}@example.test", full_name=role.title(), role=role,
                       campus_id=campus, department_id=None)


def _profile(sb, user, *, campus=CAMPUS, **academics):
    row = {"id": str(user.id), "email": user.email, "role": user.role, "campus_id": str(campus),
           "batch_year": None, "section": None, "course_id": None}
    row.update(academics)
    sb.tables["profiles"].append(row)
    return row


# --- audience: an explicit choice on every new upload -------------------------------------------------

def test_an_upload_without_an_audience_is_refused():
    with pytest.raises(DocumentError, match="Choose who can see"):
        require_audience(None, None)


def test_all_students_cannot_also_carry_a_target():
    with pytest.raises(DocumentError, match="cannot also have"):
        require_audience("all_students", AcademicMetadata(batch_year=2026))


def test_targeted_needs_at_least_one_batch_course_or_section():
    with pytest.raises(DocumentError, match="at least one"):
        require_audience("targeted", None)
    with pytest.raises(DocumentError, match="at least one"):
        require_audience("targeted", AcademicMetadata(source_person="Office"))


def test_valid_audiences_are_accepted():
    require_audience("all_students", None)
    require_audience("all_students", AcademicMetadata(source_person="Office"))
    require_audience("targeted", AcademicMetadata(batch_year=2026))
    require_audience("targeted", AcademicMetadata(section="a"))


# --- assignment: Authority only, same campus, active values only --------------------------------------

@pytest.mark.asyncio
async def test_authority_assigns_active_values_and_the_change_is_audited():
    sb = FakeDataClient()
    authority = _user("authority")
    _profile(sb, authority)
    student = _user("student")
    _profile(sb, student)
    sb.tables["filter_options"].append({"campus_id": str(CAMPUS), "kind": "batch", "value": "2026", "active": True})
    sb.tables["filter_options"].append({"campus_id": str(CAMPUS), "kind": "section", "value": "a", "active": True})
    course = uuid4()
    sb.tables["courses"].append({"id": str(course), "campus_id": str(CAMPUS), "name": "bba", "active": True})

    result = await assign_student_academics(sb=sb, actor=authority, access_token="t", student_id=student.id,
                                            batch_year=2026, section="a", course_id=course)

    assert result == {"batch_year": 2026, "section": "a", "course_id": str(course)}
    assert sb.tables["student_academic_audit"][0]["changed_by"] == str(authority.id)
    assert sb.tables["student_academic_audit"][0]["before_values"] == {"batch_year": None, "section": None, "course_id": None}


@pytest.mark.parametrize("role", ["student", "faculty", "management"])
@pytest.mark.asyncio
async def test_only_authority_can_assign(role):
    sb = FakeDataClient()
    actor = _user(role)
    _profile(sb, actor)
    student = _user("student")
    _profile(sb, student)

    with pytest.raises(DocumentForbidden):
        await assign_student_academics(sb=sb, actor=actor, access_token="t", student_id=student.id,
                                       batch_year=2026, section=None, course_id=None)
    assert sb.tables["student_academic_audit"] == []


@pytest.mark.asyncio
async def test_a_student_on_another_campus_is_not_found_to_this_authority():
    sb = FakeDataClient()
    authority = _user("authority")
    _profile(sb, authority)
    stranger = _user("student")
    _profile(sb, stranger, campus=OTHER_CAMPUS)

    with pytest.raises(DocumentNotFound):
        await assign_student_academics(sb=sb, actor=authority, access_token="t", student_id=stranger.id,
                                       batch_year=2026, section=None, course_id=None)


@pytest.mark.asyncio
async def test_an_inactive_or_unknown_value_is_refused_and_nothing_changes():
    sb = FakeDataClient()
    authority = _user("authority")
    _profile(sb, authority)
    student = _user("student")
    _profile(sb, student)
    sb.tables["filter_options"].append({"campus_id": str(CAMPUS), "kind": "batch", "value": "2025", "active": False})

    with pytest.raises(DocumentError, match="not an active option"):
        await assign_student_academics(sb=sb, actor=authority, access_token="t", student_id=student.id,
                                       batch_year=2025, section=None, course_id=None)
    row = next(r for r in sb.tables["profiles"] if r["id"] == str(student.id))
    assert row["batch_year"] is None
    assert sb.tables["student_academic_audit"] == []


@pytest.mark.asyncio
async def test_a_course_from_another_campus_is_refused():
    sb = FakeDataClient()
    authority = _user("authority")
    _profile(sb, authority)
    student = _user("student")
    _profile(sb, student)
    foreign = uuid4()
    sb.tables["courses"].append({"id": str(foreign), "campus_id": str(OTHER_CAMPUS), "name": "x", "active": True})

    with pytest.raises(DocumentError, match="not an active course"):
        await assign_student_academics(sb=sb, actor=authority, access_token="t", student_id=student.id,
                                       batch_year=None, section=None, course_id=foreign)
