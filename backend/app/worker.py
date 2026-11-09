"""Standalone document worker: `python -m app.worker`.

Run it as a separate process (for example a Render background worker) so uploads are processed
even when no web request is in flight. Several workers can run at once; the database claim uses
SKIP LOCKED, so each document is taken by one worker.
"""

import asyncio
import logging

from app.config import settings
from app.services.document_worker import run_forever
from app.services.providers import build_data_client, get_ai_client


async def main() -> None:
    if not settings.database_url or not settings.session_secret:
        raise SystemExit("DATABASE_URL and SESSION_SECRET must be set")
    if not (settings.r2_account_id and settings.r2_access_key_id and settings.r2_secret_access_key):
        raise SystemExit("R2_ACCOUNT_ID, R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY must be set")
    sb = build_data_client()
    ai = get_ai_client() if settings.gemini_api_key else None
    if ai is None:
        logging.getLogger("unibuddy.worker").warning("GEMINI_API_KEY is not set; the worker will idle")
    await run_forever(sb, ai)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
