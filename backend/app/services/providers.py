from functools import lru_cache

from fastapi import HTTPException, status

from app.ai.openai_client import OpenAIClient
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
def get_openai_client() -> OpenAIClient:
    if not settings.openai_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI service is not configured")
    return OpenAIClient(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        embedding_model=settings.openai_embedding_model,
        chat_model=settings.openai_chat_model,
    )
