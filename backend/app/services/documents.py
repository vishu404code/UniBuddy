from typing import Any
from uuid import UUID, uuid4

from app.schemas.auth import CurrentUser
from app.services.supabase_client import SupabaseClient, SupabaseError

PDF_CONTENT_TYPE = "application/pdf"
MAX_TITLE_LENGTH = 200
PUBLISH_NOT_READY = "document_not_publishable"


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


async def _store_and_queue(
    *,
    sb: SupabaseClient,
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
) -> dict[str, Any]:
    require_university_wide_permission(uploader, scope)
    validate_upload(data, content_type, title, max_bytes)
    if uploader.campus_id is None:
        raise DocumentForbidden("Your account has no campus assigned")
    if department_id is not None:
        await _check_department(sb, department_id, uploader.campus_id)

    document_id = uuid4()
    storage_path = f"{uploader.campus_id}/{document_id}.pdf"
    await sb.upload_object(storage_bucket, storage_path, data, PDF_CONTENT_TYPE)

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
        "replaces_document_id": str(replaces_document_id) if replaces_document_id else None,
    }
    try:
        await sb.insert_service("documents", [row])
    except SupabaseError:
        await _best_effort_remove_object(sb, storage_bucket, storage_path)
        raise

    rows = await sb.select_service("documents", {"select": "*", "id": f"eq.{document_id}"})
    return rows[0]


async def _best_effort_remove_object(sb: SupabaseClient, bucket: str, path: str) -> None:
    try:
        await sb.delete_object(bucket, path)
    except SupabaseError:
        pass


async def upload_document(
    *,
    sb: SupabaseClient,
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
) -> dict[str, Any]:
    return await _store_and_queue(
        sb=sb, uploader=uploader, title=title, visibility=visibility, scope=scope,
        department_id=department_id, filename=filename, data=data, max_bytes=max_bytes,
        storage_bucket=storage_bucket, replaces_document_id=None, content_type=content_type,
    )


async def _load_visible_document(sb: SupabaseClient, access_token: str, document_id: UUID) -> dict[str, Any]:
    rows = await sb.select_as_user(access_token, "documents", {"select": "*", "id": f"eq.{document_id}"})
    if not rows:
        raise DocumentNotFound("Document not found")
    return rows[0]


UNIVERSITY_WIDE_ROLES = frozenset({"authority", "super_admin"})


def require_university_wide_permission(user: CurrentUser, scope: str) -> None:
    """Only authority (and Super Admin) may create, publish or archive university-wide content.

    The database enforces the same rule with a trigger on documents, so this is not the only check.
    """
    if scope == "university_wide" and user.role not in UNIVERSITY_WIDE_ROLES:
        raise DocumentForbidden("Only authority can handle university-wide documents")


def _can_manage(user: CurrentUser, document: dict[str, Any]) -> bool:
    if str(document["uploaded_by"]) == str(user.id):
        return True
    return user.role == "authority" and str(document["campus_id"]) == str(user.campus_id)


async def replace_document(
    *,
    sb: SupabaseClient,
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
        raise DocumentForbidden("Only the uploader or same-campus authority can replace this document")
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
    )


async def archive_document(
    *,
    sb: SupabaseClient,
    user: CurrentUser,
    access_token: str,
    document_id: UUID,
) -> dict[str, Any]:
    document = await _load_visible_document(sb, access_token, document_id)
    if not _can_manage(user, document):
        raise DocumentForbidden("Only the uploader or same-campus authority can archive this document")
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
    sb: SupabaseClient,
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
    except SupabaseError as exc:
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
