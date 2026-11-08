import asyncio
from uuid import uuid4

import pymupdf
import pytest

from app.config import settings
from app.services import document_worker as worker
from app.services.supabase_client import SupabaseError
from tests.fakes import FakeAI, FakeSupabase

BUCKET = "documents"


def _pdf(text="Fee policy: pay in week two."):
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def _pending_doc(sb, data=None, attempts=0):
    doc_id = uuid4()
    path = f"campus/{doc_id}.pdf"
    sb.storage[f"{BUCKET}/{path}"] = data if data is not None else _pdf()
    sb.tables["documents"].append({
        "id": str(doc_id), "title": "Fee Policy", "storage_path": path,
        "uploaded_by": str(uuid4()), "campus_id": str(uuid4()), "scope": "campus",
        "visibility": "public_students", "publication_status": "draft",
        "processing_status": "pending", "processing_attempts": attempts, "last_error": None,
        "processing_started_at": None, "page_count": None, "created_at": "2026-11-01T10:00:00+00:00",
    })
    return doc_id


def _doc(sb, doc_id):
    return next(r for r in sb.tables["documents"] if r["id"] == str(doc_id))


async def _process(sb, ai, doc_id, max_attempts=3):
    claimed = next(r for r in sb.tables["documents"] if r["id"] == str(doc_id))
    claimed["processing_status"] = "processing"
    claimed["processing_attempts"] = claimed.get("processing_attempts", 0) + 1
    return await worker.process_document(
        sb=sb, ai=ai, document=dict(claimed), bucket=BUCKET,
        chunk_max_chars=1000, chunk_overlap_chars=100, max_attempts=max_attempts,
    )


@pytest.mark.asyncio
async def test_successful_processing_marks_ready_and_stores_page_numbered_chunks():
    sb, ai = FakeSupabase(), FakeAI()
    doc_id = _pending_doc(sb)

    status = await _process(sb, ai, doc_id)

    assert status == "ready"
    doc = _doc(sb, doc_id)
    assert doc["processing_status"] == "ready"
    assert doc["page_count"] == 1
    assert doc["last_error"] is None
    chunks = [c for c in sb.tables["document_chunks"] if c["document_id"] == str(doc_id)]
    assert chunks and all(c["page_number"] == 1 for c in chunks)


@pytest.mark.asyncio
async def test_reprocessing_replaces_old_chunks_instead_of_duplicating_them():
    sb, ai = FakeSupabase(), FakeAI()
    doc_id = _pending_doc(sb)
    sb.tables["document_chunks"].append({"document_id": str(doc_id), "chunk_index": 0, "page_number": 9,
                                         "content": "stale chunk from an interrupted run", "embedding": "[]"})

    await _process(sb, ai, doc_id)

    contents = [c["content"] for c in sb.tables["document_chunks"] if c["document_id"] == str(doc_id)]
    assert "stale chunk from an interrupted run" not in contents
    assert len(contents) == len(set(contents))


@pytest.mark.asyncio
async def test_unreadable_pdf_fails_permanently_with_a_reason():
    sb, ai = FakeSupabase(), FakeAI()
    doc_id = _pending_doc(sb, data=b"%PDF-1.4 truncated garbage")

    status = await _process(sb, ai, doc_id)

    assert status == "failed"
    assert "corrupted" in _doc(sb, doc_id)["last_error"]


@pytest.mark.asyncio
async def test_scanned_pdf_fails_with_the_ocr_reason():
    document = pymupdf.open()
    document.new_page()
    blank = document.tobytes()
    document.close()
    sb, ai = FakeSupabase(), FakeAI()
    doc_id = _pending_doc(sb, data=blank)

    status = await _process(sb, ai, doc_id)

    assert status == "failed"
    assert "OCR" in _doc(sb, doc_id)["last_error"]


@pytest.mark.asyncio
async def test_temporary_ai_failure_returns_the_document_to_the_queue():
    sb, ai = FakeSupabase(), FakeAI(fail_embed=True)
    doc_id = _pending_doc(sb)

    status = await _process(sb, ai, doc_id, max_attempts=3)

    assert status == "pending"
    doc = _doc(sb, doc_id)
    assert doc["processing_status"] == "pending"
    assert "will be retried" in doc["last_error"]


@pytest.mark.asyncio
async def test_temporary_failure_after_the_last_attempt_is_failed():
    sb, ai = FakeSupabase(), FakeAI(fail_embed=True)
    doc_id = _pending_doc(sb, attempts=3)

    status = await _process(sb, ai, doc_id, max_attempts=3)

    assert status == "failed"
    assert "gave up after 3 attempts" in _doc(sb, doc_id)["last_error"]


@pytest.mark.asyncio
async def test_storage_download_error_is_treated_as_temporary():
    sb, ai = FakeSupabase(), FakeAI()
    doc_id = _pending_doc(sb)
    sb.storage.clear()

    status = await _process(sb, ai, doc_id)

    assert status == "pending"


@pytest.mark.asyncio
async def test_unexpected_error_requeues_instead_of_crashing_the_worker(monkeypatch):
    sb, ai = FakeSupabase(), FakeAI()
    doc_id = _pending_doc(sb)

    async def boom(*args, **kwargs):
        raise RuntimeError("bug in a code path")

    monkeypatch.setattr(ai, "embed", boom)

    status = await _process(sb, ai, doc_id)

    assert status == "pending"


@pytest.mark.asyncio
async def test_run_once_claims_each_job_once_and_processes_it():
    sb, ai = FakeSupabase(), FakeAI()
    first = _pending_doc(sb)
    second = _pending_doc(sb)

    processed = await worker.run_once(sb, ai)
    again = await worker.run_once(sb, ai)

    assert processed == 2
    assert again == 0
    assert _doc(sb, first)["processing_status"] == "ready"
    assert _doc(sb, second)["processing_status"] == "ready"


@pytest.mark.asyncio
async def test_worker_does_not_claim_while_the_ai_key_is_missing(monkeypatch):
    sb, ai = FakeSupabase(), FakeAI()
    _pending_doc(sb)
    claims = []
    original = sb.rpc_service

    async def counting_rpc(function, payload):
        claims.append(function)
        return await original(function, payload)

    sb.rpc_service = counting_rpc
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "document_worker_poll_seconds", 0.01)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(worker.run_forever(sb, ai), timeout=0.2)

    assert claims == []
    assert sb.tables["documents"][0]["processing_status"] == "pending"


@pytest.mark.asyncio
async def test_claim_failure_does_not_stop_the_loop(monkeypatch):
    sb, ai = FakeSupabase(), FakeAI()
    attempts = []

    async def flaky_rpc(function, payload):
        attempts.append(function)
        if len(attempts) == 1:
            raise SupabaseError(503, "temporarily unavailable")
        return []

    sb.rpc_service = flaky_rpc
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-only")
    monkeypatch.setattr(settings, "document_worker_poll_seconds", 0.01)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(worker.run_forever(sb, ai), timeout=0.3)

    assert len(attempts) >= 2
