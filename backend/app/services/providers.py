from functools import lru_cache

from fastapi import HTTPException, status

from app.ai.gemini_client import GeminiClient
from app.config import settings
from app.services.postgres_client import PostgresClient
from app.services.supabase_client import SupabaseClient
from app.storage.objects import ObjectStore


def build_object_store() -> ObjectStore | None:
    """File storage for PDFs. R2 when configured; otherwise the Supabase bucket is used."""
    if settings.storage_backend != "r2":
        return None
    if not (settings.r2_account_id and settings.r2_access_key_id and settings.r2_secret_access_key):
        raise RuntimeError("R2 storage is selected but its settings are incomplete")
    from app.storage.r2 import R2ObjectStore, build_r2_client

    client = build_r2_client(settings.r2_account_id, settings.r2_access_key_id, settings.r2_secret_access_key)
    return R2ObjectStore(client, settings.r2_bucket)


def build_data_client():
    """The data client for the selected backend. Used by the web app and the worker."""
    if settings.data_backend == "postgres":
        if not settings.database_url or not settings.session_secret:
            raise RuntimeError("Postgres data is selected but DATABASE_URL or SESSION_SECRET is missing")
        return PostgresClient(settings.database_url, settings.session_secret, object_store=build_object_store())
    return SupabaseClient(
        settings.supabase_url or "",
        settings.supabase_secret_key or "",
        settings.supabase_publishable_key,
    )


@lru_cache
def get_supabase_client():
    if settings.data_backend == "postgres":
        if not settings.database_url or not settings.session_secret:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database access is not configured")
    elif not settings.supabase_url or not settings.supabase_secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database access is not configured")
    return build_data_client()


def get_google_verifier():
    """Hook for tests. None means the real Google verifier is used."""
    return None


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
def get_auth_admin_client():
    if settings.auth_backend == "google":
        from app.services.account_directory import PostgresAccountDirectory

        return PostgresAccountDirectory(get_supabase_client())

    from app.services.auth_admin import AuthAdminClient

    if not settings.supabase_url or not settings.supabase_secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "User provisioning is not configured")
    return AuthAdminClient(settings.supabase_url, settings.supabase_secret_key)
