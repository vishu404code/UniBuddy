from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend configuration, loaded from environment variables / .env."""

    app_name: str = "UniBuddy Backend"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"

    # Comma-separated origins allowed to call this API. Defaults to the
    # frontend's local dev server (server.js runs on :3000).
    allowed_origins: str = "http://localhost:3000,http://localhost:5173"

    # Supabase project URL, e.g. https://<project-ref>.supabase.co
    supabase_url: str | None = None
    # Supabase secret API key (sb_secret_...). Server-side only. It bypasses RLS,
    # so it must never reach the frontend or a log line.
    supabase_secret_key: str | None = None
    # Publishable key (sb_publishable_...). Used as the apikey for requests made on
    # behalf of a user, so RLS applies. Never use the secret key for those requests.
    supabase_publishable_key: str | None = None
    supabase_storage_bucket: str = "documents"

    # Cloudflare R2 (S3-compatible) for PDFs. Server-side only. Not used until the migration.
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str = "unibuddy-documents"

    # Google Gemini (GenAI SDK). Server-side only. Documents and questions share one
    # embedding model, and its output is fixed at 1536 dimensions to match the database.
    gemini_api_key: str | None = None
    gemini_embedding_model: str = "gemini-embedding-001"
    # gemini-2.5-flash returns 404 for this key's generateContent calls, so it is not used.
    gemini_chat_model: str = "gemini-3.5-flash-lite"

    # Provisioning: invitations are only sent to these email domains (exact match, comma-separated).
    # Empty means provisioning is disabled and every request fails closed.
    provisioning_allowed_email_domains: str = ""

    # Ingestion and retrieval limits. Retrieval values are starting points and
    # must be tuned against real campus documents.
    max_upload_bytes: int = 20 * 1024 * 1024
    chunk_max_chars: int = 1000
    chunk_overlap_chars: int = 150
    retrieval_top_k: int = 5
    retrieval_min_similarity: float = 0.3

    # Document worker. Claims pending uploads, so restarts and extra workers are safe.
    document_worker_enabled: bool = True
    document_worker_poll_seconds: float = 5.0
    document_worker_batch_size: int = 3
    document_lease_seconds: int = 600
    document_max_attempts: int = 3

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def provisioning_allowed_domains_set(self) -> frozenset[str]:
        return frozenset(
            domain.strip().lstrip("@").lower()
            for domain in self.provisioning_allowed_email_domains.split(",")
            if domain.strip()
        )

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


settings = Settings()
