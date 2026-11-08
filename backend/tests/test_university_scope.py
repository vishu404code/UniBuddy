from uuid import uuid4

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.middleware.auth import get_profile_repository, get_token_verifier
from app.schemas.auth import CurrentUser
from app.services.documents import (
    DocumentForbidden,
    archive_document,
    publish_document,
    replace_document,
    upload_document,
)
from app.services.providers import get_ai_client, get_supabase_client
from tests.conftest import FakeProfileRepository, make_profile
from tests.fakes import FakeAI, FakeSupabase

CAMPUS = uuid4()
BUCKET = "documents"


def _user(role):
    return CurrentUser(id=uuid4(), email=f"{role}@nst.rishihood.edu.in", full_name=role, role=role,
                       campus_id=CAMPUS, department_id=None)


def _pdf():
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "Campus notice.")
    data = d.tobytes()
    d.close()
    return data


def _seed(sb, uploader, scope, status="ready", publication="draft"):
    doc_id = uuid4()
    sb.tables["documents"].append({
        "id": str(doc_id), "title": "Notice", "storage_path": f"c/{doc_id}.pdf",
        "uploaded_by": str(uploader.id), "campus_id": str(CAMPUS), "department_id": None,
        "scope": scope, "visibility": "public_students", "publication_status": publication,
        "processing_status": status, "processing_attempts": 1, "last_error": None,
        "replaces_document_id": None, "page_count": 1, "original_filename": "n.pdf",
        "created_at": "2026-11-01T10:00:00+00:00",
    })
    sb.storage[f"{BUCKET}/c/{doc_id}.pdf"] = _pdf()
    return doc_id


async def _upload(sb, user, scope):
    return await upload_document(sb=sb, uploader=user, title="Notice", visibility="public_students", scope=scope,
                                 department_id=None, filename="n.pdf", content_type="application/pdf",
                                 data=_pdf(), max_bytes=1024 * 1024, storage_bucket=BUCKET)


@pytest.mark.asyncio
async def test_faculty_cannot_upload_university_wide_documents():
    with pytest.raises(DocumentForbidden):
        await _upload(FakeSupabase(), _user("faculty"), "university_wide")


@pytest.mark.asyncio
async def test_authority_can_upload_university_wide_documents():
    doc = await _upload(FakeSupabase(), _user("authority"), "university_wide")
    assert doc["scope"] == "university_wide"


@pytest.mark.asyncio
async def test_faculty_cannot_publish_archive_or_replace_a_university_wide_document():
    sb = FakeSupabase(visible=lambda token, table, row: True)
    faculty = _user("faculty")
    doc_id = _seed(sb, _user("authority"), "university_wide")

    with pytest.raises(DocumentForbidden):
        await publish_document(sb=sb, user=faculty, access_token="t", document_id=doc_id)
    with pytest.raises(DocumentForbidden):
        await archive_document(sb=sb, user=faculty, access_token="t", document_id=doc_id)
    with pytest.raises(DocumentForbidden):
        await replace_document(sb=sb, user=faculty, access_token="t", document_id=doc_id, title=None,
                               content_type="application/pdf", filename="n.pdf", data=_pdf(),
                               max_bytes=1024 * 1024, storage_bucket=BUCKET)


@pytest.mark.asyncio
async def test_authority_publishes_a_university_wide_document():
    sb = FakeSupabase(visible=lambda token, table, row: True)
    authority = _user("authority")
    doc_id = _seed(sb, authority, "university_wide")

    published = await publish_document(sb=sb, user=authority, access_token="t", document_id=doc_id)

    assert published["publication_status"] == "published"


def test_faculty_upload_route_refuses_university_wide_scope():
    verifier_user = _user("faculty")
    app.dependency_overrides[get_token_verifier] = lambda: type("V", (), {"verify": lambda self, t: __import__("uuid").UUID(t)})()
    app.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(
        {str(verifier_user.id): make_profile(str(verifier_user.id), role="faculty", campus_id=str(CAMPUS))})
    app.dependency_overrides[get_supabase_client] = lambda: FakeSupabase()
    app.dependency_overrides[get_ai_client] = lambda: FakeAI()
    try:
        response = TestClient(app).post(
            f"{settings.api_v1_prefix}/documents",
            headers={"Authorization": f"Bearer {verifier_user.id}"},
            data={"title": "Notice", "scope": "university_wide"},
            files={"file": ("n.pdf", _pdf(), "application/pdf")},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403


def test_faculty_publish_route_refuses_a_university_wide_document():
    faculty = _user("faculty")
    sb = FakeSupabase(visible=lambda token, table, row: True)
    doc_id = _seed(sb, _user("authority"), "university_wide")
    app.dependency_overrides[get_token_verifier] = lambda: type("V", (), {"verify": lambda self, t: __import__("uuid").UUID(t)})()
    app.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(
        {str(faculty.id): make_profile(str(faculty.id), role="faculty", campus_id=str(CAMPUS))})
    app.dependency_overrides[get_supabase_client] = lambda: sb
    try:
        response = TestClient(app).post(
            f"{settings.api_v1_prefix}/documents/{doc_id}/publish",
            headers={"Authorization": f"Bearer {faculty.id}"},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403
    assert sb.tables["documents"][0]["publication_status"] == "draft"
