"""The document worker must not stall the API while it extracts a large PDF.

Extraction and chunking run in a worker thread (app/services/document_worker.py). These tests slow the
extractor down on purpose and check that the event loop keeps running in the meantime. Local fixtures only.
"""

import asyncio
import time

import pytest

from app.services import document_worker as worker
from tests.test_document_worker import _pending_doc, _process


async def _count_ticks_while(coro, interval=0.02):
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(interval)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        result = await coro
    finally:
        task.cancel()
    return result, ticks


@pytest.mark.asyncio
async def test_slow_extraction_does_not_block_the_event_loop(monkeypatch):
    real_extract = worker.extract_pages

    def slow_extract(data):
        time.sleep(0.4)  # a large PDF, simulated
        return real_extract(data)

    monkeypatch.setattr(worker, "extract_pages", slow_extract)
    from tests.fakes import FakeAI, FakeDataClient

    sb = FakeDataClient()
    doc_id = _pending_doc(sb)
    status, ticks = await _count_ticks_while(_process(sb, FakeAI(), doc_id))

    assert status == "ready"
    assert ticks >= 5, f"event loop ran only {ticks} ticks while extraction took 0.4 s"


@pytest.mark.asyncio
async def test_slow_chunking_does_not_block_the_event_loop(monkeypatch):
    real_chunk = worker.chunk_pages

    def slow_chunk(pages, max_chars, overlap):
        time.sleep(0.4)
        return real_chunk(pages, max_chars, overlap)

    monkeypatch.setattr(worker, "chunk_pages", slow_chunk)
    from tests.fakes import FakeAI, FakeDataClient

    sb = FakeDataClient()
    doc_id = _pending_doc(sb)
    status, ticks = await _count_ticks_while(_process(sb, FakeAI(), doc_id))

    assert status == "ready"
    assert ticks >= 5, f"event loop ran only {ticks} ticks while chunking took 0.4 s"
