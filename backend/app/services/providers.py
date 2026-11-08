from functools import lru_cache

from fastapi import HTTPException, status

from app.ai.gemini_client import GeminiClient
from app.config import settings
from app.services.supabase_client import SupabaseClient


@lru_cache
def get_supabase_client() -> SupabaseClient:
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database access is not configured")
    return SupabaseClient(
        settings.supabase_url,
        settings.supabase_secret_key,
        settings.supabase_publishable_key,
    )


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
    from app.services.auth_admin import AuthAdminClient

    if not settings.supabase_url or not settings.supabase_secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "User provisioning is not configured")
    return AuthAdminClient(settings.supabase_url, settings.supabase_secret_key)
