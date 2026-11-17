"""PDF access and denial cases, Authority-only filter options, and list filters.

Fixtures only: every campus, user, document and option here is created in memory by this test file.
No real record is read or changed. The storage bucket is the server's private bucket name; the tests
never see a storage URL or key. Row-level security is simulated where a test says so."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from app.config import settings
from app.routes.announcements import list_announcements
from app.routes.documents import get_document_file, list_documents
from app.schemas.documents import DocumentOut
from app.services.documents import (
    DocumentConflict,
    DocumentError,
    DocumentForbidden,
    DocumentNotFound,
    DocumentUnavailable,
    check_pdf_access,
    read_pdf,
)
from app.services.errors import DataServiceError
from app.services.options import create_option, list_options, remove_option, set_option_active
from tests.conftest import make_profile
from tests.fakes import FakeDataClient

PDF_BYTES = b"%PDF-1.4\n% fixture document, not a real record\n%%EOF\n"
BUCKET = settings.r2_bucket


def _campus(sb, name):
    campus_id = str(uuid4())
    sb.tables["campuses"].append({"id": campus_id, "name": name, "code": f"{name.lower()}-{campus_id[:4]}"})
    return campus_id


def _user(role, campus_id):
    return make_profile(str(uuid4()), role=role, campus_id=campus_id)


def _doc(sb, uploader, default_campus, **overrides):
    """A fixture document with a stored PDF. Metadata defaults to 'not specified' (None)."""
    campus_id = overrides.pop("campus_id", default_campus)
    doc_id = str(uuid4())
    path = f"{campus_id}/{doc_id}.pdf"
    row = {
        "id": doc_id, "title": "Fixture policy", "original_filename": "fixture-policy.pdf",
        "storage_path": path, "uploaded_by": str(uploader.id), "campus_id": campus_id,
        "scope": "campus", "visibility": "public_students", "publication_status": "published",
        "processing_status": "ready", "created_at": "2026-11-10T09:00:00+00:00",
        "academic_year": None, "batch_year": None, "section": None, "course_id": None,
        "source_person": None, "page_count": 1, "department_id": None, "replaces_document_id": None,
    }
    row.update(overrides)
    sb.tables["documents"].append(row)
    sb.storage[f"{BUCKET}/{path}"] = PDF_BYTES
    return row


def _session(user):
    return SimpleNamespace(user=user, access_token=str(user.id))


# --- Who may open which PDF --------------------------------------------------------------------

def test_student_opens_a_published_public_document_of_their_campus():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    authority = _user("authority", campus)
    row = _doc(sb, authority, campus)
    check_pdf_access(_user("student", campus), row)


def test_student_opens_a_university_wide_document_from_another_campus():
    sb = FakeDataClient()
    campus, other = _campus(sb, "Sonipat"), _campus(sb, "Other")
    row = _doc(sb, _user("authority", campus), campus, scope="university_wide")
    check_pdf_access(_user("student", other), row)


@pytest.mark.parametrize("override", [
    {"publication_status": "draft"},
    {"publication_status": "archived"},
    {"visibility": "staff_only"},
    {"processing_status": "pending"},
    {"processing_status": "failed"},
    {"scope": "campus", "campus_id": "OTHER"},
])
def test_student_is_denied_drafts_archived_staff_only_unprocessed_and_other_campus_documents(override):
    sb = FakeDataClient()
    campus, other = _campus(sb, "Sonipat"), _campus(sb, "Other")
    if override.get("campus_id") == "OTHER":
        override = {**override, "campus_id": other}
    row = _doc(sb, _user("authority", campus), campus, **override)
    with pytest.raises(DocumentNotFound):
        check_pdf_access(_user("student", campus), row)


def test_faculty_opens_their_own_draft_but_not_another_faculty_members_draft():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    faculty_a = _user("faculty", campus)
    faculty_b = _user("faculty", campus)
    own = _doc(sb, faculty_a, campus, publication_status="draft", processing_status="ready")
    other = _doc(sb, faculty_b, campus, publication_status="draft", processing_status="ready")
    check_pdf_access(faculty_a, own)
    with pytest.raises(DocumentNotFound):
        check_pdf_access(faculty_a, other)


def test_faculty_opens_a_published_staff_only_document_from_authority_on_their_campus():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    row = _doc(sb, _user("authority", campus), campus, visibility="staff_only")
    check_pdf_access(_user("faculty", campus), row)


def test_authority_opens_an_archived_document_on_their_campus_but_not_another_campus():
    sb = FakeDataClient()
    campus, other = _campus(sb, "Sonipat"), _campus(sb, "Other")
    row = _doc(sb, _user("authority", campus), campus, publication_status="archived")
    check_pdf_access(_user("authority", campus), row)
    with pytest.raises(DocumentNotFound):
        check_pdf_access(_user("authority", other), row)


def test_faculty_cannot_open_an_archived_document_they_did_not_upload():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    row = _doc(sb, _user("authority", campus), campus, publication_status="archived")
    with pytest.raises(DocumentNotFound):
        check_pdf_access(_user("faculty", campus), row)


def test_processing_state_is_reported_to_staff_clearly():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    faculty = _user("faculty", campus)
    row = _doc(sb, faculty, campus, publication_status="draft", processing_status="processing")
    with pytest.raises(DocumentConflict, match="still being processed"):
        check_pdf_access(faculty, row)
    failed = _doc(sb, faculty, campus, publication_status="draft", processing_status="failed")
    with pytest.raises(DocumentConflict, match="could not be processed"):
        check_pdf_access(faculty, failed)


def test_management_cannot_open_documents():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    row = _doc(sb, _user("authority", campus), campus)
    with pytest.raises(DocumentForbidden):
        check_pdf_access(make_profile(str(uuid4()), role="management", campus_id=None), row)


# --- The file endpoint -------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_file_endpoint_streams_the_pdf_with_private_headers_and_no_storage_key():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    row = _doc(sb, _user("authority", campus), campus)

    response = await get_document_file(document_id=UUID(row["id"]), session=_session(_user("student", campus)), sb=sb)

    assert response.body == PDF_BYTES
    assert response.media_type == "application/pdf"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-disposition"].startswith("inline; filename=\"fixture-policy.pdf\"")
    assert row["storage_path"] not in str(dict(response.headers))
    assert "storage_path" not in DocumentOut.model_fields


@pytest.mark.asyncio
async def test_file_endpoint_denies_a_student_even_if_row_level_security_were_bypassed():
    """The database policy is the first check. This test makes the fake return every row, as if RLS did
    not filter it, and shows the server's own check still refuses a student the draft."""
    sb = FakeDataClient(visible=lambda token, table, row: True)
    campus = _campus(sb, "Sonipat")
    draft = _doc(sb, _user("faculty", campus), campus, publication_status="draft")
    with pytest.raises(DocumentNotFound) as caught:
        await get_document_file(document_id=UUID(draft["id"]), session=_session(_user("student", campus)), sb=sb)
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_file_endpoint_refuses_unknown_documents_without_revealing_them():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    with pytest.raises(DocumentNotFound) as caught:
        await get_document_file(document_id=uuid4(), session=_session(_user("faculty", campus)), sb=sb)
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_file_endpoint_refuses_the_management_role():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    row = _doc(sb, _user("authority", campus), campus)
    management = make_profile(str(uuid4()), role="management", campus_id=None)
    with pytest.raises(DocumentForbidden) as caught:
        await get_document_file(document_id=UUID(row["id"]), session=_session(management), sb=sb)
    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_missing_file_in_storage_is_reported_as_unavailable_not_as_a_server_error():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    row = _doc(sb, _user("authority", campus), campus)
    sb.storage.clear()
    with pytest.raises(DocumentNotFound, match="missing from storage"):
        await read_pdf(sb, BUCKET, row)


@pytest.mark.asyncio
async def test_storage_outage_is_reported_as_temporarily_unavailable():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    row = _doc(sb, _user("authority", campus), campus)

    async def broken(bucket, path):
        raise DataServiceError(503, "storage down")

    sb.download_object = broken
    with pytest.raises(DocumentUnavailable):
        await read_pdf(sb, BUCKET, row)


# --- Authority-only filter options -------------------------------------------------------------

@pytest.mark.asyncio
async def test_only_authority_adds_changes_or_removes_filter_options():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    authority = _user("authority", campus)
    faculty = _user("faculty", campus)
    student = _user("student", campus)
    option = await create_option(sb, authority, "section", "A")

    for denied in (faculty, student):
        with pytest.raises(DocumentForbidden):
            await create_option(sb, denied, "section", "C")
        with pytest.raises(DocumentForbidden):
            await set_option_active(sb, denied, UUID(option["id"]), False)
        with pytest.raises(DocumentForbidden):
            await remove_option(sb, denied, UUID(option["id"]))
    assert [row["value"] for row in sb.tables["filter_options"]] == ["A"]


@pytest.mark.asyncio
async def test_faculty_see_only_active_options_and_authority_sees_inactive_too():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    authority = _user("authority", campus)
    faculty = _user("faculty", campus)
    await create_option(sb, authority, "academic_year", "2026-27")
    retired = await create_option(sb, authority, "academic_year", "2025-26")
    await set_option_active(sb, authority, UUID(retired["id"]), False)

    assert [r["value"] for r in await list_options(sb, faculty, include_inactive=False)] == ["2026-27"]
    assert len(await list_options(sb, authority, include_inactive=True)) == 2


@pytest.mark.asyncio
async def test_options_are_unique_per_campus_and_kind_ignoring_case_and_spaces():
    sb = FakeDataClient()
    authority = _user("authority", _campus(sb, "Sonipat"))
    await create_option(sb, authority, "section", "A")
    with pytest.raises(DocumentConflict):
        await create_option(sb, authority, "section", " a ")
    await create_option(sb, authority, "batch", "2026")  # a different kind is fine


def test_batch_options_must_be_four_digit_years_in_range():
    from app.services.options import clean_option

    assert clean_option("batch", "2026") == "2026"
    for bad in ("26", "1999", "2101", "20x6", "2026 A"):
        with pytest.raises(DocumentError):
            clean_option("batch", bad)


@pytest.mark.asyncio
async def test_a_used_option_is_deactivated_and_an_unused_one_is_deleted():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    authority = _user("authority", campus)
    used = await create_option(sb, authority, "section", "B")
    unused = await create_option(sb, authority, "section", "C")
    _doc(sb, authority, campus, section="B")  # a record already carries section B

    assert (await remove_option(sb, authority, UUID(used["id"])))["action"] == "deactivated"
    assert (await remove_option(sb, authority, UUID(unused["id"])))["action"] == "deleted"
    kept = {row["value"]: row["active"] for row in sb.tables["filter_options"]}
    assert kept == {"B": False}
    assert sb.tables["documents"][0]["section"] == "B"


# --- List filters ------------------------------------------------------------------------------

async def _list(sb, user, **filters):
    base = dict(limit=50, offset=0, processing_status=None, publication_status=None, visibility=None,
                scope=None, campus_id=None, department_id=None, course_id=None, academic_year=None,
                batch_year=None, section=None, created_from=None, created_before=None)
    base.update(filters)
    return await list_documents(session=_session(user), sb=sb, **base)


@pytest.mark.asyncio
async def test_document_filters_narrow_by_metadata_and_show_unspecified_records():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    authority = _user("authority", campus)
    _doc(sb, authority, campus, title="A", academic_year="2026-27", batch_year=2026, section="A")
    _doc(sb, authority, campus, title="B", academic_year="2025-26", batch_year=2025, section="B")
    _doc(sb, authority, campus, title="C")  # not specified

    def titles(page):
        return sorted(item.title for item in page.items)

    assert titles(await _list(sb, authority, academic_year="2026-27")) == ["A"]
    assert titles(await _list(sb, authority, batch_year="2025")) == ["B"]
    assert titles(await _list(sb, authority, section="A")) == ["A"]
    assert titles(await _list(sb, authority, academic_year="unspecified")) == ["C"]
    assert titles(await _list(sb, authority, batch_year="unspecified")) == ["C"]


@pytest.mark.asyncio
async def test_document_filters_refuse_malformed_values():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    authority = _user("authority", campus)
    with pytest.raises(HTTPException) as caught:
        await _list(sb, authority, batch_year="26")
    assert caught.value.status_code == 422
    with pytest.raises(HTTPException):
        await _list(sb, authority, course_id="not-a-uuid")


@pytest.mark.asyncio
async def test_date_range_is_applied_to_the_upload_date():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    authority = _user("authority", campus)
    _doc(sb, authority, campus, title="early", created_at="2026-10-02T09:00:00+00:00")
    _doc(sb, authority, campus, title="inside", created_at="2026-11-05T09:00:00+00:00")
    _doc(sb, authority, campus, title="late", created_at="2026-11-20T09:00:00+00:00")
    from datetime import datetime, timezone

    page = await _list(sb, authority,
                       created_from=datetime(2026, 11, 1, tzinfo=timezone.utc),
                       created_before=datetime(2026, 11, 10, tzinfo=timezone.utc))

    assert [item.title for item in page.items] == ["inside"]


@pytest.mark.asyncio
async def test_announcement_filters_apply_to_the_publication_date_and_metadata():
    sb = FakeDataClient()
    campus = _campus(sb, "Sonipat")
    author = _user("authority", campus)
    base = {"audience": "all_students", "scope": "campus", "campus_id": campus, "category": "Notice",
            "body": "Fixture body.", "is_important": False, "published_by": str(author.id)}
    sb.tables["announcements"].extend([
        {**base, "id": str(uuid4()), "title": "Old", "created_at": "2026-10-01T09:00:00+00:00",
         "academic_year": "2026-27", "batch_year": 2026, "section": "A", "course_id": None},
        {**base, "id": str(uuid4()), "title": "Recent", "created_at": "2026-11-05T09:00:00+00:00",
         "academic_year": None, "batch_year": None, "section": None, "course_id": None},
    ])
    student = _user("student", campus)

    page = await list_announcements(
        session=_session(student), limit=50, offset=0, audience=None, scope=None, campus_id=None,
        is_important=None, course_id=None, academic_year="unspecified", batch_year=None, section=None,
        created_from=None, created_before=None, sb=sb,
    )
    assert [item.title for item in page.items] == ["Recent"]

    page = await list_announcements(
        session=_session(student), limit=50, offset=0, audience=None, scope=None, campus_id=None,
        is_important=None, course_id=None, academic_year=None, batch_year=None, section=None,
        created_from=None, created_before=None, sb=sb,
    )
    assert sorted(item.title for item in page.items) == ["Old", "Recent"]
