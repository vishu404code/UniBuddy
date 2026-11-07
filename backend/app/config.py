from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend configuration, loaded from environment variables / .env.

    Only Milestone 1 settings live here for now. Supabase, OpenAI, and
    storage settings will be added in later milestones as they're needed.
    """

    app_name: str = "UniBuddy Backend"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"

    # Comma-separated origins allowed to call this API. Defaults to the
    # frontend's local dev server (backend/../server.js runs on :3000).
    allowed_origins: str = "http://localhost:3000"

    # Supabase project URL, e.g. https://<project-ref>.supabase.co
    supabase_url: str | None = None
    # Server-side only. Bypasses RLS, so it is used for profile lookups and must
    # never reach the frontend or a log line.
    supabase_service_role_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


settings = Settings()
