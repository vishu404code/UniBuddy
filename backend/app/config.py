from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend configuration, loaded from environment variables / .env."""

    app_name: str = "UniBuddy Backend"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"

    # Comma-separated origins allowed to call this API. Defaults to the
    # frontend's local dev server (server.js runs on :3000).
    allowed_origins: str = "http://localhost:3000"

    # Supabase project URL, e.g. https://<project-ref>.supabase.co
    supabase_url: str | None = None
    # Supabase secret API key (sb_secret_...). Server-side only. It bypasses RLS,
    # so it must never reach the frontend or a log line.
    supabase_secret_key: str | None = None
    # Publishable key (sb_publishable_...). Used as the apikey for requests made on
    # behalf of a user, so RLS applies. Never use the secret key for those requests.
    supabase_publishable_key: str | None = None
    supabase_storage_bucket: str = "documents"

    # OpenAI. Server-side only.
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_chat_model: str = "gpt-4o-mini"

    # Ingestion and retrieval limits. Retrieval values are starting points and
    # must be tuned against real campus documents.
    max_upload_bytes: int = 20 * 1024 * 1024
    chunk_max_chars: int = 1000
    chunk_overlap_chars: int = 150
    retrieval_top_k: int = 5
    retrieval_min_similarity: float = 0.3

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


settings = Settings()
