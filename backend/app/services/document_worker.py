import asyncio
import logging
from typing import Any

import httpx

from app.ai.chunking import chunk_pages
from app.ai.openai_client import OpenAIClient, OpenAIError
from app.ai.pdf_extractor import PdfProcessingError, extract_pages
from app.config import settings
from app.services.supabase_client import SupabaseClient, SupabaseError

logger = logging.getLogger("unibuddy.worker")


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(value) for value in vector) + "]"


async def _finish_failed(sb: SupabaseClient, document: dict[str, Any], reason: str) -> None:
    await sb.update_service(
        "documents",
        {"id": f"eq.{document['id']}"},
        {"processing_status": "failed", "last_error": reason, "processing_started_at": None},
    )


async def _requeue_or_fail(sb: SupabaseClient, document: dict[str, Any], reason: str, max_attempts: int) -> str:
    exhausted = int(document.get("processing_attempts") or 0) >= max_attempts
    status = "failed" if exhausted else "pending"
    message = reason if not exhausted else f"{reason} (gave up after {max_attempts} attempts)"
    await sb.update_service(
        "documents",
        {"id": f"eq.{document['id']}"},
        {"processing_status": status, "last_error": message, "processing_started_at": None},
    )
    return status


async def process_document(
    *,
    sb: SupabaseClient,
    ai: OpenAIClient,
    document: dict[str, Any],
    bucket: str,
    chunk_max_chars: int,
    chunk_overlap_chars: int,
    max_attempts: int,
) -> str:
    """Process one claimed document and return its new processing status.

    Re-running is safe: old chunks are deleted before new ones are inserted, so a
    document interrupted after inserting chunks is rebuilt cleanly on the next attempt.
    """
    document_id = document["id"]
    try:
        data = await sb.download_object(bucket, document["storage_path"])
        extracted = extract_pages(data)
        chunks = chunk_pages(extracted.pages, chunk_max_chars, chunk_overlap_chars)
        vectors = await ai.embed([chunk.content for chunk in chunks])

        rows = [
            {
                "document_id": str(document_id),
                "chunk_index": chunk.chunk_index,
                "page_number": chunk.page_number,
                "content": chunk.content,
                "embedding": _vector_literal(vector),
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        await sb.delete_service("document_chunks", {"document_id": f"eq.{document_id}"})
        await sb.insert_service_batched("document_chunks", rows)
        await sb.update_service(
            "documents",
            {"id": f"eq.{document_id}"},
            {
                "processing_status": "ready",
                "page_count": extracted.page_count,
                "last_error": None,
                "processing_started_at": None,
            },
        )
        return "ready"
    except PdfProcessingError as exc:
        await _finish_failed(sb, document, str(exc))
        return "failed"
    except (OpenAIError, SupabaseError, httpx.HTTPError) as exc:
        logger.warning("Document %s processing attempt failed: %s", document_id, type(exc).__name__)
        reason = "Processing failed temporarily; it will be retried"
        if isinstance(exc, OpenAIError):
            reason = "The AI service did not respond; processing will be retried"
        return await _requeue_or_fail(sb, document, reason, max_attempts)
    except Exception:
        logger.exception("Unexpected error while processing document %s", document_id)
        return await _requeue_or_fail(sb, document, "Unexpected processing error; it will be retried", max_attempts)


async def claim_jobs(sb: SupabaseClient, limit: int) -> list[dict[str, Any]]:
    return await sb.rpc_service(
        "claim_document_jobs",
        {
            "p_limit": limit,
            "p_lease_seconds": settings.document_lease_seconds,
            "p_max_attempts": settings.document_max_attempts,
        },
    )


async def run_once(sb: SupabaseClient, ai: OpenAIClient) -> int:
    jobs = await claim_jobs(sb, settings.document_worker_batch_size)
    for job in jobs:
        await process_document(
            sb=sb,
            ai=ai,
            document=job,
            bucket=settings.supabase_storage_bucket,
            chunk_max_chars=settings.chunk_max_chars,
            chunk_overlap_chars=settings.chunk_overlap_chars,
            max_attempts=settings.document_max_attempts,
        )
    return len(jobs)


async def run_forever(sb: SupabaseClient, ai: OpenAIClient) -> None:
    waiting_logged = False
    while True:
        try:
            if not settings.openai_api_key:
                if not waiting_logged:
                    logger.warning("OPENAI_API_KEY is not set; documents will wait in the queue")
                    waiting_logged = True
                await asyncio.sleep(settings.document_worker_poll_seconds)
                continue
            waiting_logged = False
            processed = await run_once(sb, ai)
            if processed == 0:
                await asyncio.sleep(settings.document_worker_poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Document worker iteration failed; retrying")
            await asyncio.sleep(settings.document_worker_poll_seconds)
