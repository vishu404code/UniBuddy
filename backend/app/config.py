from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend configuration, loaded from environment variables and backend/.env.

    Secrets stay server-side. Never place them in frontend code, Git, or logs.
    """

    app_name: str = "UniBuddy Backend"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"

    # Comma-separated origins allowed to call this API (the frontend dev server and any hosted frontend).
    allowed_origins: str = "http://localhost:3000,http://localhost:5173,https://vishu404code.github.io"

    # Neon PostgreSQL (with pgvector). Server-side only. Connect as a non-superuser role that is
    # granted authenticated and service_role (see docs/SETUP.md).
    database_url: str | None = None

    # Signs UniBuddy's own session tokens. Server-side only. At least 32 random characters.
    session_secret: str | None = None

    # Google OAuth client ID (public). Used to check that a Google ID token was issued for this app.
    google_client_id: str | None = None

    # Cloudflare R2 (S3-compatible) for private PDFs. Server-side only.
    storage_backend: str = "r2"
    local_storage_dir: str = ".local-data/objects"
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str = "unibuddy-documents"

    # Any S3-compatible private bucket, such as Neon Object Storage (STORAGE_BACKEND=s3).
    # Path-style addressing and SigV4 are used. Server-side only.
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_bucket: str = "unibuddy-documents"

    # Google Gemini (GenAI SDK). Server-side only. Documents and questions share one
    # embedding model, and its output is fixed at 1536 dimensions to match the database.
    gemini_api_key: str | None = None
    gemini_embedding_model: str = "gemini-embedding-001"
    # gemini-2.5-flash returns 404 for the configured key's generateContent calls, so it is not used.
    gemini_chat_model: str = "gemini-3.5-flash-lite"

    # Ingestion and retrieval limits. Retrieval values are starting points and must be tuned.
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
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


settings = Settings()
