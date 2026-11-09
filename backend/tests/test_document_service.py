from uuid import uuid4

import pymupdf
import pytest

from app.schemas.auth import CurrentUser
from app.services.documents import (
    DocumentConflict,
    DocumentError,
    DocumentForbidden,
    DocumentNotFound,
    archive_document,
    publish_document,
    replace_document,
    upload_document,
)
from app.services.errors import DataServiceError
from tests.fakes import FakeDataClient

CAMPUS = uuid4()
OTHER_CAMPUS = uuid4()
DEPT = uuid4()
BUCKET = "documents"


def _user(role, campus=CAMPUS, user_id=None):
    return CurrentUser(id=user_id or uuid4(), email=f"{role}@example.com", full_name=role.title(),
                       role=role, campus_id=campus, department_id=None)


def _pdf(text="Fee policy: pay in week two."):
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def _visible_to_uploader(token, table, row):
    return row.get("uploaded_by") == token


async def _upload(sb, uploader, data=None, **overrides):
    params = dict(sb=sb, uploader=uploader, title="Fee Policy", visibility="public_students", scope="campus",
                  department_id=None, filename="fee.pdf", content_type="application/pdf",
                  data=data if data is not None else _pdf(), max_bytes=1024 * 1024, storage_bucket=BUCKET)
    params.update(overrides)
    return await upload_document(**params)


def _seed_ready_document(sb, uploader, *, status="published", processing="ready", **extra):
    doc_id = uuid4()
    row = {
        "id": str(doc_id), "title": "Fee Policy", "storage_path": f"c/{doc_id}.pdf",
        "uploaded_by": str(uploader.id), "campus_id": str(CAMPUS), "department_id": None,
        "scope": "campus", "visibility": "public_students", "publication_status": status,
        "processing_status": processing, "processing_attempts": 1, "last_error": None,
        "replaces_document_id": None, "page_count": 1, "original_filename": "x.pdf",
        "created_at": "2026-11-01T10:00:00+00:00",
    }
    row.update(extra)
    sb.tables["documents"].append(row)
    sb.storage[f"{BUCKET}/{row['storage_path']}"] = _pdf()
    return doc_id


@pytest.mark.asyncio
async def test_upload_stores_file_and_queues_a_pending_draft_without_calling_ai():
    sb = FakeDataClient()
    uploader = _user("faculty")

    doc = await _upload(sb, uploader)

    assert doc["processing_status"] == "pending"
    assert doc["publication_status"] == "draft"
    assert doc["uploaded_by"] == str(uploader.id)
    assert f"{BUCKET}/{CAMPUS}/{doc['id']}.pdf" in sb.storage
    assert sb.tables["document_chunks"] == []


@pytest.mark.asyncio
async def test_non_pdf_upload_is_rejected_before_storage():
    sb = FakeDataClient()
    with pytest.raises(DocumentError, match="Only PDF"):
        await _upload(sb, _user("faculty"), content_type="image/png")
    assert sb.tables["documents"] == [] and sb.storage == {}


@pytest.mark.asyncio
async def test_renamed_non_pdf_bytes_are_rejected():
    with pytest.raises(DocumentError, match="not a PDF"):
        await _upload(FakeDataClient(), _user("faculty"), data=b"<html>not a pdf</html>")


@pytest.mark.asyncio
async def test_oversize_upload_is_rejected():
    with pytest.raises(DocumentError, match="larger than"):
        await _upload(FakeDataClient(), _user("faculty"), max_bytes=10)


@pytest.mark.asyncio
async def test_department_from_another_campus_is_rejected():
    sb = FakeDataClient()
    sb.tables["departments"].append({"id": str(DEPT), "campus_id": str(OTHER_CAMPUS), "name": "CS"})
    with pytest.raises(DocumentError, match="does not belong to your campus"):
        await _upload(sb, _user("faculty"), department_id=DEPT)


@pytest.mark.asyncio
async def test_storage_failure_stores_nothing_in_the_database():
    sb = FakeDataClient()
    sb.fail_storage = True
    with pytest.raises(DataServiceError):
        await _upload(sb, _user("faculty"))
    assert sb.tables["documents"] == []


@pytest.mark.asyncio
async def test_database_failure_removes_the_orphaned_file():
    sb = FakeDataClient()

    async def broken_insert(table, rows):
        raise DataServiceError(500, "database down")

    sb.insert_service = broken_insert
    with pytest.raises(DataServiceError):
        await _upload(sb, _user("faculty"))
    assert sb.storage == {}


@pytest.mark.asyncio
async def test_uploader_publishes_their_ready_draft_through_the_database_function():
    uploader = _user("faculty")
    sb = FakeDataClient(visible=_visible_to_uploader)
    doc_id = _seed_ready_document(sb, uploader, status="draft")

    published = await publish_document(sb=sb, user=uploader, access_token=str(uploader.id), document_id=doc_id)

    assert published["publication_status"] == "published"


@pytest.mark.asyncio
async def test_faculty_cannot_publish_another_members_draft():
    uploader, other = _user("faculty"), _user("faculty")
    sb = FakeDataClient(visible=_visible_to_uploader)
    doc_id = _seed_ready_document(sb, uploader, status="draft")

    with pytest.raises(DocumentNotFound):
        await publish_document(sb=sb, user=other, access_token=str(other.id), document_id=doc_id)


@pytest.mark.asyncio
async def test_publishing_a_pending_document_is_a_conflict():
    uploader = _user("faculty")
    sb = FakeDataClient(visible=_visible_to_uploader)
    doc = await _upload(sb, uploader)

    with pytest.raises(DocumentConflict, match="not ready"):
        await publish_document(sb=sb, user=uploader, access_token=str(uploader.id), document_id=doc["id"])


@pytest.mark.asyncio
async def test_replacement_is_a_new_draft_linked_to_the_old_version():
    uploader = _user("faculty")
    sb = FakeDataClient(visible=_visible_to_uploader)
    old_id = _seed_ready_document(sb, uploader, status="published")

    new = await replace_document(sb=sb, user=uploader, access_token=str(uploader.id), document_id=old_id,
                                 title=None, content_type="application/pdf", filename="v2.pdf",
                                 data=_pdf("Revised fee policy."), max_bytes=1024 * 1024, storage_bucket=BUCKET)

    assert new["replaces_document_id"] == str(old_id)
    assert new["publication_status"] == "draft"
    assert new["processing_status"] == "pending"
    assert new["title"] == "Fee Policy"
    old = next(r for r in sb.tables["documents"] if r["id"] == str(old_id))
    assert old["publication_status"] == "published"


@pytest.mark.asyncio
async def test_publishing_a_replacement_archives_the_old_version_in_one_step():
    uploader = _user("faculty")
    sb = FakeDataClient(visible=_visible_to_uploader)
    old_id = _seed_ready_document(sb, uploader, status="published")
    new = await replace_document(sb=sb, user=uploader, access_token=str(uploader.id), document_id=old_id,
                                 title="v2", content_type="application/pdf", filename="v2.pdf",
                                 data=_pdf("v2"), max_bytes=1024 * 1024, storage_bucket=BUCKET)
    next(r for r in sb.tables["documents"] if r["id"] == new["id"])["processing_status"] = "ready"

    await publish_document(sb=sb, user=uploader, access_token=str(uploader.id), document_id=new["id"])

    statuses = {r["id"]: r["publication_status"] for r in sb.tables["documents"]}
    assert statuses[new["id"]] == "published"
    assert statuses[str(old_id)] == "archived"


@pytest.mark.asyncio
async def test_only_one_replacement_can_be_in_progress():
    uploader = _user("faculty")
    sb = FakeDataClient(visible=_visible_to_uploader)
    old_id = _seed_ready_document(sb, uploader, status="published")
    kwargs = dict(sb=sb, user=uploader, access_token=str(uploader.id), document_id=old_id, title=None,
                  content_type="application/pdf", filename="v2.pdf", data=_pdf("v2"),
                  max_bytes=1024 * 1024, storage_bucket=BUCKET)
    await replace_document(**kwargs)

    with pytest.raises(DocumentConflict, match="already in progress"):
        await replace_document(**kwargs)


@pytest.mark.asyncio
async def test_archived_document_cannot_be_replaced():
    uploader = _user("faculty")
    sb = FakeDataClient(visible=_visible_to_uploader)
    old_id = _seed_ready_document(sb, uploader, status="archived")

    with pytest.raises(DocumentConflict, match="Archived"):
        await replace_document(sb=sb, user=uploader, access_token=str(uploader.id), document_id=old_id, title=None,
                               content_type="application/pdf", filename="v2.pdf", data=_pdf("v2"),
                               max_bytes=1024 * 1024, storage_bucket=BUCKET)


@pytest.mark.asyncio
async def test_archive_marks_a_document_archived_and_is_idempotent():
    uploader = _user("faculty")
    sb = FakeDataClient(visible=_visible_to_uploader)
    doc_id = _seed_ready_document(sb, uploader, status="published")

    first = await archive_document(sb=sb, user=uploader, access_token=str(uploader.id), document_id=doc_id)
    second = await archive_document(sb=sb, user=uploader, access_token=str(uploader.id), document_id=doc_id)

    assert first["publication_status"] == "archived"
    assert second["publication_status"] == "archived"


@pytest.mark.asyncio
async def test_authority_outside_the_campus_cannot_archive():
    uploader = _user("faculty")
    other_authority = _user("authority", campus=OTHER_CAMPUS)
    sb = FakeDataClient(visible=lambda token, table, row: True)
    doc_id = _seed_ready_document(sb, uploader, status="published")

    with pytest.raises(DocumentForbidden):
        await archive_document(sb=sb, user=other_authority, access_token="t", document_id=doc_id)
