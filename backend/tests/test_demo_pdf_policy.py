"""Regression tests for two blockers found while running the local Faculty-to-Student PDF demo.

1. Document upload failed: a Python list was sent as JSON, but documents.tags is a Postgres text[] column.
   Lists for that column must go as native arrays; other lists stay JSON (for example jsonb citations).
2. The finalized UI opens PDFs through GET /documents/{id}/file, which this line did not have. The route is the
   one the deployed line runs: students get published, public, ready documents for their campus or university-wide;
   staff get what their scope allows; management is refused. Fixtures only."""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from psycopg.types.json import Json

from app.config import settings
from app.main import app
from app.middleware.auth import get_profile_repository, get_token_verifier
from app.services.postgres_client import _adapt
from app.services.providers import get_data_client
from tests.conftest import FakeProfileRepository, make_profile
from tests.fakes import FakeDataClient

CAMPUS_A = str(uuid4())
CAMPUS_B = str(uuid4())
STUDENT_A = str(uuid4())
STUDENT_B = str(uuid4())
FACULTY = str(uuid4())
MANAGEMENT = str(uuid4())
DOC_ID = str(uuid4())
PDF_BYTES = b"%PDF-1.7\nfixture pdf bytes\n%%EOF"
PATH = "fixture/doc.pdf"


class _Verifier:
    def verify(self, token):
        return UUID(token)


def _campus_of(user_id):
    return {STUDENT_A: CAMPUS_A, STUDENT_B: CAMPUS_B, FACULTY: CAMPUS_A, MANAGEMENT: CAMPUS_A}.get(user_id)


def _doc(**changes):
    row = {
        "id": DOC_ID, "campus_id": CAMPUS_A, "uploaded_by": FACULTY, "title": "FIXTURE Policy",
        "mime_type": "application/pdf", "storage_path": PATH, "publication_status": "published",
        "processing_status": "ready", "visibility": "public_students", "scope": "campus",
        "original_filename": "FIXTURE_Policy.pdf",
    }
    row.update(changes)
    return row


def _db(store=True, **changes):
    sb = FakeDataClient(visible=lambda token, table, row: table != "documents" or row.get("campus_id") == _campus_of(token))
    sb.tables["documents"].append(_doc(**changes))
    if store:
        sb.storage[f"{settings.r2_bucket}/{PATH}"] = PDF_BYTES
    return sb


def _get_file(sb, who):
    profiles = {
        STUDENT_A: make_profile(STUDENT_A, role="student", campus_id=CAMPUS_A),
        STUDENT_B: make_profile(STUDENT_B, role="student", campus_id=CAMPUS_B),
        FACULTY: make_profile(FACULTY, role="faculty", campus_id=CAMPUS_A),
        MANAGEMENT: make_profile(MANAGEMENT, role="management", campus_id=CAMPUS_A),
    }
    app.dependency_overrides[get_token_verifier] = lambda: _Verifier()
    app.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(profiles)
    app.dependency_overrides[get_data_client] = lambda: sb
    try:
        return TestClient(app).get(f"{settings.api_v1_prefix}/documents/{DOC_ID}/file", headers={"Authorization": f"Bearer {who}"})
    finally:
        app.dependency_overrides.clear()


# --- 1. Upload: the text[] tags column ---------------------------------------------------------------

def test_tags_for_the_text_array_column_go_as_a_native_list():
    assert _adapt([], "documents", "tags") == []
    assert _adapt(["fees", "2026"], "documents", "tags") == ["fees", "2026"]


def test_other_lists_still_go_as_json_such_as_message_citations():
    assert isinstance(_adapt([{"title": "FIXTURE", "page": 1}], "messages", "citations"), Json)
    assert isinstance(_adapt([], "messages", "citations"), Json)


def test_dicts_are_unchanged_and_scalars_pass_through():
    assert isinstance(_adapt({"a": 1}, "documents", "tags"), Json)
    assert _adapt("text", "documents", "title") == "text"


# --- 2. The file route: the deployed policy --------------------------------------------------------------

def test_a_student_on_the_same_campus_opens_a_published_ready_public_pdf():
    response = _get_file(_db(), STUDENT_A)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == PDF_BYTES
    assert response.headers["cache-control"] == "private, no-store"


def test_a_student_on_another_campus_gets_not_found():
    assert _get_file(_db(), STUDENT_B).status_code == 404


def test_a_student_never_gets_a_draft():
    assert _get_file(_db(publication_status="draft"), STUDENT_A).status_code == 404


def test_a_student_never_gets_a_staff_only_document():
    assert _get_file(_db(visibility="staff_only"), STUDENT_A).status_code == 404


def test_a_student_never_gets_a_document_that_is_still_processing():
    assert _get_file(_db(processing_status="processing"), STUDENT_A).status_code == 404


def test_management_cannot_open_document_files():
    assert _get_file(_db(), MANAGEMENT).status_code == 403


def test_the_uploading_faculty_can_open_their_own_draft_once_it_is_ready():
    assert _get_file(_db(publication_status="draft"), FACULTY).status_code == 200


def test_a_document_without_stored_content_is_not_served():
    assert _get_file(_db(store=False), STUDENT_A).status_code == 404
