from typing import Any
from uuid import UUID, uuid4

from app.ai.chunking import chunk_pages
from app.ai.openai_client import OpenAIClient, OpenAIError
from app.ai.pdf_extractor import PdfProcessingError, extract_pages
from app.schemas.auth import CurrentUser
from app.services.supabase_client import SupabaseClient, SupabaseError

PDF_CONTENT_TYPE = "application/pdf"
MAX_TITLE_LENGTH = 200


class DocumentError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class DocumentNotFound(DocumentError):
    status_code = 404


class DocumentForbidden(DocumentError):
    status_code = 403


class DocumentConflict(DocumentError):
    status_code = 409


class DocumentProcessingFailed(DocumentError):
    status_code = 422


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(value) for value in vector) + "]"


def validate_upload(data: bytes, content_type: str | None, title: str, max_bytes: int) -> None:
    if not title.strip() or len(title.strip()) > MAX_TITLE_LENGTH:
        raise DocumentError(f"Title must be 1 to {MAX_TITLE_LENGTH} characters")
    if content_type != PDF_CONTENT_TYPE:
        raise DocumentError("Only PDF uploads are supported")
    if not data:
        raise DocumentError("File is empty")
    if len(data) > max_bytes:
        raise DocumentError(f"File is larger than {max_bytes // (1024 * 1024)} MB")
    if not data.startswith(b"%PDF-"):
        raise DocumentError("File content is not a PDF")


async def _check_department(sb: SupabaseClient, department_id: UUID, campus_id: UUID) -> None:
    rows = await sb.select_service(
        "departments",
        {"select": "id", "id": f"eq.{department_id}", "campus_id": f"eq.{campus_id}"},
    )
    if not rows:
        raise DocumentError("Department does not belong to your campus")


async def _mark_failed(sb: SupabaseClient, document_id: UUID) -> None:
    await sb.update_service(
        "documents",
        {"id": f"eq.{document_id}"},
        {"processing_status": "failed"},
    )


async def ingest_document(
    *,
    sb: SupabaseClient,
    ai: OpenAIClient,
    uploader: CurrentUser,
    title: str,
    visibility: str,
    scope: str,
    department_id: UUID | None,
    filename: str | None,
    content_type: str | None,
    data: bytes,
    max_bytes: int,
    chunk_max_chars: int,
    chunk_overlap_chars: int,
    storage_bucket: str,
) -> dict[str, Any]:
    validate_upload(data, content_type, title, max_bytes)
    if uploader.campus_id is None:
        raise DocumentForbidden("Your account has no campus assigned")
    if department_id is not None:
        await _check_department(sb, department_id, uploader.campus_id)

    document_id = uuid4()
    storage_path = f"{uploader.campus_id}/{document_id}.pdf"
    row: dict[str, Any] = {
        "id": str(document_id),
        "title": title.strip(),
        "original_filename": filename,
        "mime_type": PDF_CONTENT_TYPE,
        "file_size_bytes": len(data),
        "storage_path": storage_path,
        "uploaded_by": str(uploader.id),
        "campus_id": str(uploader.campus_id),
        "department_id": str(department_id) if department_id else None,
        "scope": scope,
        "visibility": visibility,
        "processing_status": "pending",
        "publication_status": "draft",
    }
    await sb.insert_service("documents", [row])

    try:
        await sb.upload_object(storage_bucket, storage_path, data, PDF_CONTENT_TYPE)
        await sb.update_service("documents", {"id": f"eq.{document_id}"}, {"processing_status": "processing"})

        extracted = extract_pages(data)
        chunks = chunk_pages(extracted.pages, chunk_max_chars, chunk_overlap_chars)
        vectors = await ai.embed([chunk.content for chunk in chunks])

        chunk_rows = [
            {
                "id": str(uuid4()),
                "document_id": str(document_id),
                "chunk_index": chunk.chunk_index,
                "page_number": chunk.page_number,
                "content": chunk.content,
                "embedding": _vector_literal(vector),
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        await sb.insert_service("document_chunks", chunk_rows)
        await sb.update_service(
            "documents",
            {"id": f"eq.{document_id}"},
            {"processing_status": "ready", "page_count": extracted.page_count},
        )
    except PdfProcessingError as exc:
        await _mark_failed(sb, document_id)
        raise DocumentProcessingFailed(str(exc)) from exc
    except OpenAIError as exc:
        await _mark_failed(sb, document_id)
        raise DocumentProcessingFailed("Embedding generation failed; try uploading again later") from exc
    except SupabaseError:
        await _mark_failed(sb, document_id)
        raise
    except Exception:
        await _mark_failed(sb, document_id)
        raise

    rows = await sb.select_service("documents", {"select": "*", "id": f"eq.{document_id}"})
    return rows[0]


async def publish_document(
    *,
    sb: SupabaseClient,
    user: CurrentUser,
    access_token: str,
    document_id: UUID,
) -> dict[str, Any]:
    rows = await sb.select_as_user(
        access_token,
        "documents",
        {"select": "*", "id": f"eq.{document_id}"},
    )
    if not rows:
        raise DocumentNotFound("Document not found")
    document = rows[0]

    if user.role == "faculty" and str(document["uploaded_by"]) != str(user.id):
        raise DocumentForbidden("Only the uploader can publish a faculty draft")
    if document["processing_status"] != "ready":
        raise DocumentConflict("Document is not ready to publish")
    if document["publication_status"] != "draft":
        raise DocumentConflict("Only draft documents can be published")

    updated = await sb.update_service(
        "documents",
        {
            "id": f"eq.{document_id}",
            "publication_status": "eq.draft",
            "processing_status": "eq.ready",
        },
        {"publication_status": "published"},
    )
    if not updated:
        raise DocumentConflict("Document changed while publishing; reload and try again")
    return updated[0]
