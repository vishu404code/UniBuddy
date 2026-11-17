import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from app.schemas.auth import CurrentUser
from app.services.postgres_client import PostgresClient
from fastapi import HTTPException

from app.services.errors import DataServiceError

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


class DocumentUnavailable(DocumentError):
    status_code = 503


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


async def _check_department(sb: PostgresClient, department_id: UUID, campus_id: UUID) -> None:
    rows = await sb.select_service(
        "departments",
        {"select": "id", "id": f"eq.{department_id}", "campus_id": f"eq.{campus_id}"},
    )
    if not rows:
        raise DocumentError("Department does not belong to your campus")


async def _check_course(sb: PostgresClient, course_id: UUID, campus_id: UUID) -> None:
    """A document can only use an active course from the uploader's own campus."""
    rows = await sb.select_service(
        "courses",
        {"select": "id,active", "id": f"eq.{course_id}", "campus_id": f"eq.{campus_id}"},
    )
    if not rows or not rows[0]["active"]:
        raise DocumentError("Choose an active course from your campus")


@dataclass(frozen=True)
class AcademicMetadata:
    """Optional browsing fields. They help people find a document; they never change who can read it."""

    academic_year: str | None = None
    batch_year: int | None = None
    section: str | None = None
    course_id: UUID | None = None
    source_person: str | None = None


def _clean_text(value: str | None, limit: int) -> str | None:
    if value is None or not value.strip():
        return None
    cleaned = " ".join(value.split())
    if len(cleaned) > limit:
        raise DocumentError(f"Text must be {limit} characters or fewer")
    return cleaned


def clean_metadata(
    *,
    academic_year: str | None,
    batch_year: int | None,
    section: str | None,
    course_id: UUID | None,
    source_person: str | None,
) -> AcademicMetadata:
    if batch_year is not None and not (2000 <= batch_year <= 2100):
        raise DocumentError("Batch year must be between 2000 and 2100")
    return AcademicMetadata(
        academic_year=_clean_text(academic_year, 20),
        batch_year=batch_year,
        section=_clean_text(section, 10),
        course_id=course_id,
        source_person=_clean_text(source_person, 120),
    )


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
    metadata: AcademicMetadata | None = None,
    validate_options: bool = True,
) -> dict[str, Any]:
    require_university_wide_permission(uploader, scope)
    validate_upload(data, content_type, title, max_bytes)
    if uploader.campus_id is None:
        raise DocumentForbidden("Your account has no campus assigned")
    if department_id is not None:
        await _check_department(sb, department_id, uploader.campus_id)
    meta = metadata or AcademicMetadata()
    if meta.course_id is not None:
        await _check_course(sb, meta.course_id, uploader.campus_id)
    if validate_options:
        await check_metadata_options(sb, uploader.campus_id, meta)

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
        "academic_year": meta.academic_year,
        "batch_year": meta.batch_year,
        "section": meta.section,
        "course_id": str(meta.course_id) if meta.course_id else None,
        "source_person": meta.source_person,
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
    metadata: AcademicMetadata | None = None,
) -> dict[str, Any]:
    return await _store_and_queue(
        sb=sb, uploader=uploader, title=title, visibility=visibility, scope=scope,
        department_id=department_id, filename=filename, data=data, max_bytes=max_bytes,
        storage_bucket=storage_bucket, replaces_document_id=None, content_type=content_type,
        metadata=metadata,
    )


async def _load_visible_document(sb: PostgresClient, access_token: str, document_id: UUID) -> dict[str, Any]:
    rows = await sb.select_as_user(access_token, "documents", {"select": "*", "id": f"eq.{document_id}"})
    if not rows:
        raise DocumentNotFound("Document not found")
    return rows[0]


UNIVERSITY_WIDE_ROLES = frozenset({"authority", "faculty", "super_admin"})


def require_university_wide_permission(user: CurrentUser, scope: str) -> None:
    """Faculty, Authority and Super Admin may create, publish or archive university-wide documents.
    Students and anyone without a staff profile may not. The database trigger enforces the same rule."""
    if scope == "university_wide" and user.role not in UNIVERSITY_WIDE_ROLES:
        raise DocumentForbidden("Only faculty or authority can handle university-wide documents")


def _can_manage(user: CurrentUser, document: dict[str, Any]) -> bool:
    if str(document["uploaded_by"]) == str(user.id):
        return True
    return user.role == "authority" and str(document["campus_id"]) == str(user.campus_id)


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
        # A new version keeps the metadata of the version it replaces, so it is not re-checked against
        # today's options: an option retired since then must not block the replacement.
        validate_options=False,
        metadata=AcademicMetadata(
            academic_year=original.get("academic_year"),
            batch_year=original.get("batch_year"),
            section=original.get("section"),
            course_id=UUID(str(original["course_id"])) if original.get("course_id") else None,
            source_person=original.get("source_person"),
        ),
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


async def stored_bytes_estimate(sb) -> int:
    """Sum of recorded PDF sizes (an estimate of object storage in use). Rows are read with the
    service role, so every document counts, including archived ones that still have a file."""
    rows = await sb.select_service("documents", {"select": "file_size_bytes"})
    return sum(int(r.get("file_size_bytes") or 0) for r in rows)



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


# --- Filter options --------------------------------------------------------------------------

OPTION_LABELS = {"academic_year": "academic year", "batch": "batch year", "section": "section"}


async def require_active_option(sb: PostgresClient, campus_id: UUID, kind: str, value: str) -> None:
    """New selections must be active options on the uploader's campus. Existing records are not re-checked."""
    rows = await sb.select_service(
        "filter_options", {"select": "value,active", "campus_id": f"eq.{campus_id}", "kind": f"eq.{kind}"}
    )
    wanted = value.strip().lower()
    if not any(row["active"] and str(row["value"]).strip().lower() == wanted for row in rows):
        raise DocumentError(f"Choose an active {OPTION_LABELS[kind]} from the list")


async def check_metadata_options(sb: PostgresClient, campus_id: UUID | None, meta: AcademicMetadata) -> None:
    if campus_id is None:
        if meta.academic_year or meta.batch_year is not None or meta.section:
            raise DocumentForbidden("Your account has no campus assigned")
        return
    if meta.academic_year:
        await require_active_option(sb, campus_id, "academic_year", meta.academic_year)
    if meta.batch_year is not None:
        await require_active_option(sb, campus_id, "batch", str(meta.batch_year))
    if meta.section:
        await require_active_option(sb, campus_id, "section", meta.section)


# --- PDF access ------------------------------------------------------------------------------

PROCESSING_MESSAGES = {
    "pending": "This PDF is waiting to be processed. It can be opened when processing is complete.",
    "processing": "This PDF is still being processed. It can be opened when processing is complete.",
    "failed": "This PDF could not be processed, so it cannot be opened. Upload it again.",
}


def _staff_can_open(user: CurrentUser, document: dict[str, Any]) -> bool:
    """Mirrors can_read_document() in the database: the uploader always; published documents for their
    campus or university-wide; drafts and archived documents only for Authority on their campus."""
    same_campus_or_univ = document["scope"] == "university_wide" or str(document.get("campus_id")) == str(user.campus_id)
    if str(document["uploaded_by"]) == str(user.id):
        return True
    if document["publication_status"] == "published":
        return same_campus_or_univ
    return user.role == "authority" and same_campus_or_univ


def check_pdf_access(user: CurrentUser, document: dict[str, Any]) -> None:
    """Students get published, public, ready documents for their campus or university-wide only.
    Anything else is reported as not available, so drafts and other audiences are not revealed."""
    if user.role == "student":
        allowed = (
            document["publication_status"] == "published"
            and document["visibility"] == "public_students"
            and document["processing_status"] == "ready"
            and (document["scope"] == "university_wide" or str(document.get("campus_id")) == str(user.campus_id))
        )
        if not allowed:
            raise DocumentNotFound("This document is not available to your account.")
    elif user.role in ("faculty", "authority"):
        if not _staff_can_open(user, document):
            raise DocumentNotFound("This document is not available to your account.")
    else:
        raise DocumentForbidden("Your role cannot open documents")
    status = document["processing_status"]
    if status != "ready":
        raise DocumentConflict(PROCESSING_MESSAGES.get(status, "This PDF cannot be opened right now."))


async def read_pdf(sb: PostgresClient, bucket: str, document: dict[str, Any]) -> bytes:
    """Reads the file with the server's storage access. The bucket stays private; the client never
    receives a storage key or a storage URL."""
    try:
        return await sb.download_object(bucket, document["storage_path"])
    except DataServiceError as exc:
        if exc.status_code == 404:
            raise DocumentNotFound("The PDF file is missing from storage. Ask Authority to upload it again.") from exc
        raise DocumentUnavailable("File storage is unavailable right now. Try again in a few minutes.") from exc


# --- Filters shared by the document and announcement lists ----------------------------------

UNSPECIFIED = "unspecified"

def text_filter(value: str, limit: int) -> str:
    if value == UNSPECIFIED:
        return "is.null"
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > limit:
        raise HTTPException(422, f"filter value must be 1 to {limit} characters")
    return f"eq.{cleaned}"

def batch_filter(value: str) -> str:
    if value == UNSPECIFIED:
        return "is.null"
    if not (len(value) == 4 and value.isdigit() and 2000 <= int(value) <= 2100):
        raise HTTPException(422, "batch must be a four-digit year, or unspecified")
    return f"eq.{int(value)}"

def course_filter(value: str) -> str:
    if value == UNSPECIFIED:
        return "is.null"
    try:
        return f"eq.{UUID(value)}"
    except ValueError as exc:
        raise HTTPException(422, "course must be an id, or unspecified") from exc

async def attach_course_names(sb: PostgresClient, access_token: str, rows: list[dict]) -> None:
    """Course names come from the courses table under the caller's own access. A course the caller
    may not read gets no name."""
    ids = sorted({str(row["course_id"]) for row in rows if row.get("course_id")})
    names: dict[str, str] = {}
    if ids:
        courses = await sb.select_as_user(access_token, "courses", {"select": "id,name", "id": f"in.({','.join(ids)})"})
        names = {str(course["id"]): course["name"] for course in courses}
    for row in rows:
        row["course_name"] = names.get(str(row["course_id"])) if row.get("course_id") else None
