from uuid import uuid4

import pymupdf
import pytest

from app.schemas.auth import CurrentUser
from app.services.documents import (
    DocumentConflict,
    DocumentError,
    DocumentForbidden,
    DocumentProcessingFailed,
    ingest_document,
    publish_document,
)
from tests.fakes import FakeAI, FakeSupabase

CAMPUS = uuid4()
OTHER_CAMPUS = uuid4()
DEPT = uuid4()


def _user(role, campus=CAMPUS, user_id=None):
    return CurrentUser(
        id=user_id or uuid4(), email=f"{role}@example.com", full_name=role.title(),
        role=role, campus_id=campus, department_id=None,
    )


def _pdf(text="Fee policy: pay in week two."):
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def _seed_department(sb, campus=CAMPUS):
    sb.tables["departments"].append({"id": str(DEPT), "campus_id": str(campus), "name": "CS"})


async def _ingest(sb, ai, uploader, data=None, **overrides):
    params = dict(
        sb=sb, ai=ai, uploader=uploader, title="Fee Policy", visibility="public_students",
        scope="campus", department_id=None, filename="fee.pdf", content_type="application/pdf",
        data=data if data is not None else _pdf(), max_bytes=1024 * 1024,
        chunk_max_chars=1000, chunk_overlap_chars=100, storage_bucket="documents",
    )
    params.update(overrides)
    return await ingest_document(**params)


@pytest.mark.asyncio
async def test_successful_upload_stores_file_chunks_and_marks_ready():
    sb, ai = FakeSupabase(), FakeAI()
    uploader = _user("faculty")

    doc = await _ingest(sb, ai, uploader)

    assert doc["processing_status"] == "ready"
    assert doc["publication_status"] == "draft"
    assert doc["page_count"] == 1
    assert doc["uploaded_by"] == str(uploader.id)
    assert doc["campus_id"] == str(CAMPUS)
    assert f"documents/{CAMPUS}/{doc['id']}.pdf" in sb.storage
    chunks = sb.tables["document_chunks"]
    assert len(chunks) >= 1
    assert chunks[0]["page_number"] == 1
    assert chunks[0]["embedding"].startswith("[") and chunks[0]["embedding"].endswith("]")


@pytest.mark.asyncio
async def test_non_pdf_upload_is_rejected_before_storage():
    sb, ai = FakeSupabase(), FakeAI()

    with pytest.raises(DocumentError, match="Only PDF"):
        await _ingest(sb, ai, _user("faculty"), content_type="image/png")
    assert sb.tables["documents"] == []
    assert sb.storage == {}


@pytest.mark.asyncio
async def test_renamed_non_pdf_bytes_are_rejected():
    sb, ai = FakeSupabase(), FakeAI()

    with pytest.raises(DocumentError, match="not a PDF"):
        await _ingest(sb, ai, _user("faculty"), data=b"<html>not a pdf</html>")


@pytest.mark.asyncio
async def test_oversize_upload_is_rejected():
    sb, ai = FakeSupabase(), FakeAI()

    with pytest.raises(DocumentError, match="larger than"):
        await _ingest(sb, ai, _user("faculty"), max_bytes=10)


@pytest.mark.asyncio
async def test_department_from_another_campus_is_rejected():
    sb, ai = FakeSupabase(), FakeAI()
    _seed_department(sb, campus=OTHER_CAMPUS)

    with pytest.raises(DocumentError, match="does not belong to your campus"):
        await _ingest(sb, ai, _user("faculty"), department_id=DEPT)


@pytest.mark.asyncio
async def test_uploader_without_campus_is_forbidden():
    sb, ai = FakeSupabase(), FakeAI()

    with pytest.raises(DocumentForbidden):
        await _ingest(sb, ai, _user("faculty", campus=None))


@pytest.mark.asyncio
async def test_scanned_pdf_is_marked_failed_and_reported():
    document = pymupdf.open()
    document.new_page()
    blank = document.tobytes()
    document.close()
    sb, ai = FakeSupabase(), FakeAI()

    with pytest.raises(DocumentProcessingFailed, match="OCR"):
        await _ingest(sb, ai, _user("faculty"), data=blank)
    assert sb.tables["documents"][0]["processing_status"] == "failed"
    assert sb.tables["document_chunks"] == []


@pytest.mark.asyncio
async def test_embedding_failure_marks_document_failed():
    sb, ai = FakeSupabase(), FakeAI(fail_embed=True)

    with pytest.raises(DocumentProcessingFailed):
        await _ingest(sb, ai, _user("faculty"))
    assert sb.tables["documents"][0]["processing_status"] == "failed"


@pytest.mark.asyncio
async def test_storage_failure_marks_document_failed_and_raises():
    sb, ai = FakeSupabase(), FakeAI()
    sb.fail_storage = True

    from app.services.supabase_client import SupabaseError

    with pytest.raises(SupabaseError):
        await _ingest(sb, ai, _user("faculty"))
    assert sb.tables["documents"][0]["processing_status"] == "failed"


def _visible_to_uploader(token, table, row):
    return True


@pytest.mark.asyncio
async def test_uploader_can_publish_their_ready_draft():
    uploader = _user("faculty")
    sb, ai = FakeSupabase(visible=_visible_to_uploader), FakeAI()
    doc = await _ingest(sb, ai, uploader)

    published = await publish_document(sb=sb, user=uploader, access_token="t", document_id=doc["id"])

    assert published["publication_status"] == "published"


@pytest.mark.asyncio
async def test_faculty_cannot_publish_another_faculty_members_draft():
    uploader = _user("faculty")
    other = _user("faculty")
    sb, ai = FakeSupabase(visible=_visible_to_uploader), FakeAI()
    doc = await _ingest(sb, ai, uploader)

    with pytest.raises(DocumentForbidden):
        await publish_document(sb=sb, user=other, access_token="t", document_id=doc["id"])


@pytest.mark.asyncio
async def test_publishing_twice_is_a_conflict():
    uploader = _user("faculty")
    sb, ai = FakeSupabase(visible=_visible_to_uploader), FakeAI()
    doc = await _ingest(sb, ai, uploader)
    await publish_document(sb=sb, user=uploader, access_token="t", document_id=doc["id"])

    with pytest.raises(DocumentConflict):
        await publish_document(sb=sb, user=uploader, access_token="t", document_id=doc["id"])


@pytest.mark.asyncio
async def test_failed_document_cannot_be_published():
    uploader = _user("faculty")
    sb, ai = FakeSupabase(visible=_visible_to_uploader), FakeAI(fail_embed=True)
    with pytest.raises(DocumentProcessingFailed):
        await _ingest(sb, ai, uploader)
    doc_id = sb.tables["documents"][0]["id"]

    with pytest.raises(DocumentConflict, match="not ready"):
        await publish_document(sb=sb, user=uploader, access_token="t", document_id=doc_id)
