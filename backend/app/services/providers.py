"""Shared clients for the API and the worker. Everything here is server-side."""

from functools import lru_cache

from fastapi import HTTPException, status

from app.ai.gemini_client import GeminiClient
from app.config import settings
from app.services.account_directory import AccountDirectory
from app.services.postgres_client import PostgresClient
from app.storage.objects import ObjectStore

R2_SETTINGS_MISSING = "R2 storage is not configured"
DATABASE_SETTINGS_MISSING = "Database access is not configured"


def _r2_configured() -> bool:
    return bool(settings.r2_account_id and settings.r2_access_key_id and settings.r2_secret_access_key)


LOCAL_STORAGE_IN_PRODUCTION = "Local file storage is for laptop demos only; production must use R2"


def _storage_configured() -> bool:
    if settings.storage_backend == "local":
        return bool(settings.local_storage_dir) and settings.app_env != "production"
    return settings.storage_backend == "r2" and _r2_configured()


def build_object_store() -> ObjectStore:
    """Build local-only demo storage or production Cloudflare R2 storage."""
    if settings.storage_backend == "local":
        if settings.app_env == "production":
            # Hosted hosts such as Render have temporary disks; PDFs there would not survive a restart.
            raise RuntimeError(LOCAL_STORAGE_IN_PRODUCTION)
        from app.storage.local import LocalObjectStore

        return LocalObjectStore(settings.local_storage_dir)
    if settings.storage_backend != "r2":
        raise RuntimeError("unsupported storage backend")
    if not _r2_configured():
        raise RuntimeError(R2_SETTINGS_MISSING)
    from app.storage.r2 import R2ObjectStore, build_r2_client

    client = build_r2_client(settings.r2_account_id, settings.r2_access_key_id, settings.r2_secret_access_key)
    return R2ObjectStore(client, settings.r2_bucket)


def build_data_client() -> PostgresClient:
    """The Neon-backed data client, with R2 for files. Used by the web app and the worker."""
    if not settings.database_url or not settings.session_secret:
        raise RuntimeError(DATABASE_SETTINGS_MISSING)
    return PostgresClient(settings.database_url, settings.session_secret, object_store=build_object_store())


@lru_cache
def get_data_client() -> PostgresClient:
    if not settings.database_url or not settings.session_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, DATABASE_SETTINGS_MISSING)
    if not _storage_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, R2_SETTINGS_MISSING)
    return build_data_client()


@lru_cache
def get_ai_client() -> GeminiClient:
    if not settings.gemini_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI service is not configured")
    return GeminiClient(
        api_key=settings.gemini_api_key,
        embedding_model=settings.gemini_embedding_model,
        chat_model=settings.gemini_chat_model,
    )


@lru_cache
def get_account_directory() -> AccountDirectory:
    return AccountDirectory(get_data_client())


def get_google_verifier():
    """Hook for tests. None means the real Google verifier is used."""
    return None
