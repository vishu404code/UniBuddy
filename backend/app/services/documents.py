from typing import Any
from uuid import UUID, uuid4

from app.schemas.auth import CurrentUser
from app.services.errors import DataServiceError
from app.services.postgres_client import PostgresClient

PDF_CONTENT_TYPE = "application/pdf"
MAX_TITLE_LENGTH = 200
PUBLISH_NOT_READY = "document_not_publishable"
UNIVERSITY_WIDE_ROLES = frozenset({"authority", "super_admin", "management"})


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


def validate_upload(
    data: bytes, content_type: str | None, title: str, max_bytes: int, filename: str | None = None
) -> str:
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
    return PDF_CONTENT_TYPE


async def _check_department(sb: PostgresClient, department_id: UUID, campus_id: UUID) -> None:
    rows = await sb.select_service(
        "departments",
        {"select": "id", "id": f"eq.{department_id}", "campus_id": f"eq.{campus_id}"},
    )
    if not rows:
        raise DocumentError("Department does not belong to your campus")


async def _store_and_queue(
    *,
    sb: PostgresClient,
    uploader: CurrentUser,
    title: str,
    visibility: str,
    scope: str,
    department_id: UUID | None,
    filename: str | None,
    data: bytes,
    max_bytes: int,
    storage_bucket: str,
    replaces_document_id: UUID | None,
    content_type: str | None,
    category: str | None = "General",
    description: str | None = None,
    effective_date: str | None = None,
    expiry_date: str | None = None,
    tags: list[str] | None = None,
    batch_year: int | None = None,
    course: str | None = None,
    course_id: str | None = None,
    section: str | None = None,
) -> dict[str, Any]:
    require_university_wide_permission(uploader, scope)
    detected_mime = validate_upload(data, content_type, title, max_bytes, filename)
    if uploader.campus_id is None and scope != "university_wide":
        raise DocumentForbidden("Your account has no campus assigned")
    if department_id is not None and uploader.campus_id is not None:
        await _check_department(sb, department_id, uploader.campus_id)

    document_id = uuid4()
    campus_prefix = str(uploader.campus_id) if uploader.campus_id else "university_wide"
    ext = (filename or "").lower().split(".")[-1] if "." in (filename or "") else "pdf"
    storage_path = f"{campus_prefix}/{document_id}.{ext}"
    await sb.upload_object(storage_bucket, storage_path, data, detected_mime)

    row: dict[str, Any] = {
        "id": str(document_id),
        "title": title.strip(),
        "item_type": "file",
        "category": category or "General",
        "description": description.strip() if description else None,
        "original_filename": filename,
        "mime_type": detected_mime,
        "file_size_bytes": len(data),
        "storage_path": storage_path,
        "uploaded_by": str(uploader.id),
        "campus_id": str(uploader.campus_id) if uploader.campus_id else None,
        "department_id": str(department_id) if department_id else None,
        "scope": scope,
        "visibility": visibility,
        "processing_status": "pending",
        "publication_status": "draft",
        "effective_date": effective_date,
        "expiry_date": expiry_date,
        "tags": tags or [],
        "batch_year": batch_year,
        "course": course,
        "course_id": course_id or course,
        "section": section,
        "replaces_document_id": str(replaces_document_id) if replaces_document_id else None,
    }
    try:
        await sb.insert_service("documents", [row])
    except DataServiceError:
        await _best_effort_remove_object(sb, storage_bucket, storage_path)
        raise

    rows = await sb.select_service("documents", {"select": "*", "id": f"eq.{document_id}"})
    return rows[0]


async def _best_effort_remove_object(sb: PostgresClient, bucket: str, path: str) -> None:
    try:
        await sb.delete_object(bucket, path)
    except DataServiceError:
        pass


async def upload_document(
    *,
    sb: PostgresClient,
    uploader: CurrentUser,
    title: str,
    visibility: str,
    scope: str,
    department_id: UUID | None,
    filename: str | None,
    content_type: str | None,
    data: bytes,
    max_bytes: int,
    storage_bucket: str,
    category: str | None = "General",
    description: str | None = None,
    effective_date: str | None = None,
    expiry_date: str | None = None,
    tags: list[str] | None = None,
    batch_year: int | None = None,
    course: str | None = None,
    course_id: str | None = None,
    section: str | None = None,
) -> dict[str, Any]:
    return await _store_and_queue(
        sb=sb,
        uploader=uploader,
        title=title,
        visibility=visibility,
        scope=scope,
        department_id=department_id,
        filename=filename,
        data=data,
        max_bytes=max_bytes,
        storage_bucket=storage_bucket,
        replaces_document_id=None,
        content_type=content_type,
        category=category,
        description=description,
        effective_date=effective_date,
        expiry_date=expiry_date,
        tags=tags,
        batch_year=batch_year,
        course=course,
        course_id=course_id,
        section=section,
    )


async def create_text_content(
    *,
    sb: PostgresClient,
    user: CurrentUser,
    title: str,
    content: str,
    category: str = "General",
    description: str | None = None,
    department_id: UUID | None = None,
    scope: str = "campus",
    visibility: str = "public_students",
    publication_status: str = "draft",
    effective_date: str | None = None,
    expiry_date: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    require_university_wide_permission(user, scope)
    if not title.strip() or len(title.strip()) > MAX_TITLE_LENGTH:
        raise DocumentError(f"Title must be 1 to {MAX_TITLE_LENGTH} characters")
    cleaned_content = content.strip()
    if not cleaned_content:
        raise DocumentError("Content must not be empty")
    if user.campus_id is None and scope != "university_wide":
        raise DocumentForbidden("Your account has no campus assigned")
    if department_id is not None and user.campus_id is not None:
        await _check_department(sb, department_id, user.campus_id)

    document_id = uuid4()
    row: dict[str, Any] = {
        "id": str(document_id),
        "title": title.strip(),
        "item_type": "text_content",
        "category": category or "General",
        "description": description.strip() if description else None,
        "raw_content": cleaned_content,
        "original_filename": f"{title.strip()[:30]}.txt",
        "mime_type": "text/plain",
        "file_size_bytes": len(cleaned_content.encode("utf-8")),
        "storage_path": "",
        "uploaded_by": str(user.id),
        "campus_id": str(user.campus_id) if user.campus_id else None,
        "department_id": str(department_id) if department_id else None,
        "scope": scope,
        "visibility": visibility,
        "processing_status": "pending",
        "publication_status": publication_status,
        "effective_date": effective_date,
        "expiry_date": expiry_date,
        "tags": tags or [],
    }
    await sb.insert_service("documents", [row])
    rows = await sb.select_service("documents", {"select": "*", "id": f"eq.{document_id}"})
    return rows[0]


async def update_text_content(
    *,
    sb: PostgresClient,
    user: CurrentUser,
    access_token: str,
    document_id: UUID,
    title: str | None = None,
    content: str | None = None,
    category: str | None = None,
    description: str | None = None,
    department_id: UUID | None = None,
    scope: str | None = None,
    visibility: str | None = None,
    publication_status: str | None = None,
    effective_date: str | None = None,
    expiry_date: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    original = await _load_visible_document(sb, access_token, document_id)
    if not _can_manage(user, original):
        raise DocumentForbidden("You do not have permission to edit this content")
    if scope:
        require_university_wide_permission(user, scope)

    updates: dict[str, Any] = {}
    if title is not None:
        if not title.strip() or len(title.strip()) > MAX_TITLE_LENGTH:
            raise DocumentError(f"Title must be 1 to {MAX_TITLE_LENGTH} characters")
        updates["title"] = title.strip()
    if category is not None:
        updates["category"] = category
    if description is not None:
        updates["description"] = description
    if scope is not None:
        updates["scope"] = scope
    if visibility is not None:
        updates["visibility"] = visibility
    if publication_status is not None:
        updates["publication_status"] = publication_status
    if effective_date is not None:
        updates["effective_date"] = effective_date
    if expiry_date is not None:
        updates["expiry_date"] = expiry_date
    if tags is not None:
        updates["tags"] = tags
    if department_id is not None:
        updates["department_id"] = str(department_id) if department_id else None

    if content is not None:
        cleaned = content.strip()
        if not cleaned:
            raise DocumentError("Content must not be empty")
        updates["raw_content"] = cleaned
        updates["file_size_bytes"] = len(cleaned.encode("utf-8"))
        updates["processing_status"] = "pending"
        updates["processing_attempts"] = 0
        updates["last_error"] = None

    if updates:
        updated = await sb.update_service("documents", {"id": f"eq.{document_id}"}, updates)
        return updated[0] if updated else original
    return original


async def update_document_metadata(
    *,
    sb: PostgresClient,
    user: CurrentUser,
    access_token: str,
    document_id: UUID,
    title: str | None = None,
    category: str | None = None,
    description: str | None = None,
    department_id: UUID | None = None,
    scope: str | None = None,
    visibility: str | None = None,
    publication_status: str | None = None,
    effective_date: str | None = None,
    expiry_date: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    original = await _load_visible_document(sb, access_token, document_id)
    if not _can_manage(user, original):
        raise DocumentForbidden("You do not have permission to edit this document")
    if scope:
        require_university_wide_permission(user, scope)

    updates: dict[str, Any] = {}
    if title is not None:
        if not title.strip() or len(title.strip()) > MAX_TITLE_LENGTH:
            raise DocumentError(f"Title must be 1 to {MAX_TITLE_LENGTH} characters")
        updates["title"] = title.strip()
    if category is not None:
        updates["category"] = category
    if description is not None:
        updates["description"] = description
    if scope is not None:
        updates["scope"] = scope
    if visibility is not None:
        updates["visibility"] = visibility
    if publication_status is not None:
        updates["publication_status"] = publication_status
    if effective_date is not None:
        updates["effective_date"] = effective_date
    if expiry_date is not None:
        updates["expiry_date"] = expiry_date
    if tags is not None:
        updates["tags"] = tags
    if department_id is not None:
        updates["department_id"] = str(department_id) if department_id else None

    if updates:
        updated = await sb.update_service("documents", {"id": f"eq.{document_id}"}, updates)
        return updated[0] if updated else original
    return original


async def delete_document(
    *,
    sb: PostgresClient,
    user: CurrentUser,
    access_token: str,
    document_id: UUID,
    storage_bucket: str,
) -> dict[str, Any]:
    document = await _load_visible_document(sb, access_token, document_id)
    if not _can_manage(user, document):
        raise DocumentForbidden("You do not have permission to delete this document")
    require_university_wide_permission(user, document.get("scope", "campus"))

    # 1. Clean up chunks
    try:
        await sb.delete_service("document_chunks", {"document_id": f"eq.{document_id}"})
    except Exception:
        pass

    # 2. Clean up storage object
    storage_path = document.get("storage_path")
    if storage_path:
        await _best_effort_remove_object(sb, storage_bucket, storage_path)

    # 3. Delete document row
    await sb.delete_service("documents", {"id": f"eq.{document_id}"})
    return {"status": "deleted", "id": str(document_id)}


async def unpublish_document(
    *,
    sb: PostgresClient,
    user: CurrentUser,
    access_token: str,
    document_id: UUID,
) -> dict[str, Any]:
    document = await _load_visible_document(sb, access_token, document_id)
    if not _can_manage(user, document):
        raise DocumentForbidden("You do not have permission to unpublish this document")
    require_university_wide_permission(user, document.get("scope", "campus"))
    if document.get("publication_status") == "draft":
        return document
    updated = await sb.update_service(
        "documents",
        {"id": f"eq.{document_id}"},
        {"publication_status": "draft"},
    )
    return updated[0] if updated else document


async def reprocess_document(
    *,
    sb: PostgresClient,
    user: CurrentUser,
    access_token: str,
    document_id: UUID,
) -> dict[str, Any]:
    document = await _load_visible_document(sb, access_token, document_id)
    if not _can_manage(user, document):
        raise DocumentForbidden("You do not have permission to reprocess this document")
    require_university_wide_permission(user, document.get("scope", "campus"))
    updated = await sb.update_service(
        "documents",
        {"id": f"eq.{document_id}"},
        {"processing_status": "pending", "processing_attempts": 0, "last_error": None},
    )
    return updated[0] if updated else document


async def get_knowledge_stats(
    sb: PostgresClient,
    access_token: str,
) -> dict[str, int]:
    rows = await sb.select_as_user(
        access_token, "documents", {"select": "id,item_type,publication_status,processing_status"}
    )
    total_items = len(rows)
    total_documents = sum(1 for r in rows if r.get("item_type") != "text_content")
    total_text_content = sum(1 for r in rows if r.get("item_type") == "text_content")
    published_count = sum(1 for r in rows if r.get("publication_status") == "published")
    draft_count = sum(1 for r in rows if r.get("publication_status") == "draft")
    archived_count = sum(1 for r in rows if r.get("publication_status") == "archived")
    processing_count = sum(
        1 for r in rows if r.get("processing_status") in ("pending", "processing")
    )
    failed_count = sum(1 for r in rows if r.get("processing_status") == "failed")
    return {
        "total_items": total_items,
        "total_documents": total_documents,
        "total_text_content": total_text_content,
        "published_count": published_count,
        "draft_count": draft_count,
        "archived_count": archived_count,
        "processing_count": processing_count,
        "failed_count": failed_count,
    }


async def _load_visible_document(sb: PostgresClient, access_token: str, document_id: UUID) -> dict[str, Any]:
    rows = await sb.select_as_user(access_token, "documents", {"select": "*", "id": f"eq.{document_id}"})
    if not rows:
        raise DocumentNotFound("Document not found")
    return rows[0]


def require_university_wide_permission(user: CurrentUser, scope: str) -> None:
    if scope == "university_wide" and user.role not in UNIVERSITY_WIDE_ROLES:
        raise DocumentForbidden("Only authority or management can handle university-wide documents")


def _can_manage(user: CurrentUser, document: dict[str, Any]) -> bool:
    if str(document["uploaded_by"]) == str(user.id):
        return True
    if user.role in ("authority", "management", "super_admin"):
        if document.get("scope") == "university_wide" or user.cross_campus_record_access:
            return True
        return str(document.get("campus_id")) == str(user.campus_id)
    return False


async def replace_document(
    *,
    sb: PostgresClient,
    user: CurrentUser,
    access_token: str,
    document_id: UUID,
    title: str | None,
    content_type: str | None,
    filename: str | None,
    data: bytes,
    max_bytes: int,
    storage_bucket: str,
) -> dict[str, Any]:
    original = await _load_visible_document(sb, access_token, document_id)
    if not _can_manage(user, original):
        raise DocumentForbidden("Only authorized staff can replace this document")
    require_university_wide_permission(user, original["scope"])
    if original["publication_status"] == "archived":
        raise DocumentConflict("Archived documents cannot be replaced")
    if original["processing_status"] != "ready":
        raise DocumentConflict("Wait for the current version to finish processing before replacing it")

    pending = await sb.select_service(
        "documents",
        {
            "select": "id",
            "replaces_document_id": f"eq.{document_id}",
            "publication_status": "eq.draft",
        },
    )
    if pending:
        raise DocumentConflict("A replacement for this document is already in progress")

    return await _store_and_queue(
        sb=sb,
        uploader=user,
        title=title or original["title"],
        visibility=original["visibility"],
        scope=original["scope"],
        department_id=UUID(str(original["department_id"])) if original["department_id"] else None,
        filename=filename,
        data=data,
        max_bytes=max_bytes,
        storage_bucket=storage_bucket,
        replaces_document_id=document_id,
        content_type=content_type,
        category=original.get("category"),
        description=original.get("description"),
    )


async def archive_document(
    *,
    sb: PostgresClient,
    user: CurrentUser,
    access_token: str,
    document_id: UUID,
) -> dict[str, Any]:
    document = await _load_visible_document(sb, access_token, document_id)
    if not _can_manage(user, document):
        raise DocumentForbidden("Only authorized staff can archive this document")
    require_university_wide_permission(user, document["scope"])
    if document["publication_status"] == "archived":
        return document
    updated = await sb.update_service(
        "documents",
        {"id": f"eq.{document_id}", "publication_status": "neq.archived"},
        {"publication_status": "archived"},
    )
    return updated[0] if updated else document


async def publish_document(
    *,
    sb: PostgresClient,
    user: CurrentUser,
    access_token: str,
    document_id: UUID,
) -> dict[str, Any]:
    document = await _load_visible_document(sb, access_token, document_id)
    if user.role == "faculty" and str(document["uploaded_by"]) != str(user.id):
        raise DocumentForbidden("Only the uploader can publish a faculty draft")
    require_university_wide_permission(user, document["scope"])
    if document["processing_status"] != "ready":
        raise DocumentConflict("Document is not ready to publish")
    if document["publication_status"] != "draft":
        raise DocumentConflict("Only draft documents can be published")

    try:
        published = await sb.rpc_service("publish_document_version", {"p_document_id": str(document_id)})
    except DataServiceError as exc:
        if PUBLISH_NOT_READY in exc.detail:
            raise DocumentConflict("Document changed before it could be published; reload and try again") from exc
        raise
    return published


def processing_note(document: dict[str, Any], ai_configured: bool) -> str | None:
    if document["processing_status"] == "pending" and not ai_configured:
        return "Waiting for the AI service to be configured before this document can be processed"
    if document["processing_status"] == "failed":
        return document.get("last_error")
    return None


async def restore_document(
    *,
    sb: PostgresClient,
    user: CurrentUser,
    access_token: str,
    document_id: UUID,
) -> dict[str, Any]:
    """Brings an archived document back as a draft, so it can be published again. The same record is
    reused: no file is uploaded. It is refused while another active copy of the same file exists."""
    document = await _load_visible_document(sb, access_token, document_id)
    if not _can_manage(user, document):
        raise DocumentForbidden("Only the uploader or same-campus authority can restore this document")
    require_university_wide_permission(user, document["scope"])
    if document["publication_status"] != "archived":
        raise DocumentConflict("Only archived documents can be restored")
    if document["processing_status"] != "ready":
        raise DocumentConflict("Document is not ready to restore")
    active_copies = await sb.select_service(
        "documents",
        {
            "select": "id,title",
            "original_filename": f"eq.{document['original_filename']}",
            "file_size_bytes": f"eq.{document['file_size_bytes']}",
            "publication_status": "neq.archived",
            "id": f"neq.{document_id}",
            "limit": "1",
        },
    )
    if active_copies:
        raise DocumentConflict(
            f"This file is already active as \"{active_copies[0]['title']}\". "
            "Restore is refused so the library does not hold two copies."
        )
    updated = await sb.update_service(
        "documents",
        {"id": f"eq.{document_id}", "publication_status": "eq.archived"},
        {"publication_status": "draft"},
    )
    if not updated:
        raise DocumentConflict("Document changed; reload and try again")
    return updated[0]


async def set_document_scope(
    *,
    sb: PostgresClient,
    user: CurrentUser,
    access_token: str,
    document_id: UUID,
    scope: str,
) -> dict[str, Any]:
    """Changes who an unpublished draft is for. Authority only: an existing draft's scope is an Authority decision."""
    if user.role != "authority":
        raise DocumentForbidden("Only authority can change the scope of an existing document")
    document = await _load_visible_document(sb, access_token, document_id)
    if not _can_manage(user, document):
        raise DocumentForbidden("Only the uploader or same-campus authority can change this document")
    require_university_wide_permission(user, scope)
    if document["publication_status"] != "draft":
        raise DocumentConflict("Only draft documents can change scope. Restore the document first if needed")
    if document["scope"] == scope:
        return document
    updated = await sb.update_service(
        "documents",
        {"id": f"eq.{document_id}", "publication_status": "eq.draft"},
        {"scope": scope},
    )
    if not updated:
        raise DocumentConflict("Document changed; reload and try again")
    return updated[0]