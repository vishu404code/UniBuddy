"""Standalone document worker: `python -m app.worker`.

Run it as a separate process (for example a Render background worker) so uploads
are processed even when no web request is in flight. Several workers can run at
once; the database claim uses SKIP LOCKED, so each document is taken by one worker.
"""

import asyncio
import logging

from app.ai.openai_client import OpenAIClient
from app.config import settings
from app.services.document_worker import run_forever
from app.services.supabase_client import SupabaseClient


def build_clients() -> tuple[SupabaseClient, OpenAIClient | None]:
    sb = SupabaseClient(settings.supabase_url, settings.supabase_secret_key, settings.supabase_publishable_key)
    ai = None
    if settings.openai_api_key:
        ai = OpenAIClient(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            embedding_model=settings.openai_embedding_model,
            chat_model=settings.openai_chat_model,
        )
    return sb, ai


async def main() -> None:
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SECRET_KEY must be set")
    sb, ai = build_clients()
    if ai is None:
        logging.getLogger("unibuddy.worker").warning("OPENAI_API_KEY is not set; the worker will idle")
    await run_forever(sb, ai)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
