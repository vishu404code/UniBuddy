"""Standalone document worker: `python -m app.worker`.

Run it as a separate process (for example a Render background worker) so uploads
are processed even when no web request is in flight. Several workers can run at
once; the database claim uses SKIP LOCKED, so each document is taken by one worker.
"""

import asyncio
import logging

from app.ai.gemini_client import GeminiClient
from app.config import settings
from app.services.document_worker import run_forever


def build_clients():
    from app.services.providers import build_data_client

    sb = build_data_client()
    ai = None
    if settings.gemini_api_key:
        ai = GeminiClient(
            api_key=settings.gemini_api_key,
            embedding_model=settings.gemini_embedding_model,
            chat_model=settings.gemini_chat_model,
        )
    return sb, ai


async def main() -> None:
    if settings.data_backend == "postgres":
        if not settings.database_url or not settings.session_secret:
            raise SystemExit("DATABASE_URL and SESSION_SECRET must be set")
    elif not settings.supabase_url or not settings.supabase_secret_key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SECRET_KEY must be set")
    sb, ai = build_clients()
    if ai is None:
        logging.getLogger("unibuddy.worker").warning("GEMINI_API_KEY is not set; the worker will idle")
    await run_forever(sb, ai)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
