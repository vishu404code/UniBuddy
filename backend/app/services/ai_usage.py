"""Usage metadata for model calls: one row per call.

A row holds when the call happened, which operation it was, the model name, the request count, and the token
counts the model returned (NULL when it did not return them). It never holds a question, an answer, a
transcript, a user id or an email. A failure to record never fails the caller.
"""

import logging
from typing import Any
from uuid import uuid4

logger = logging.getLogger("unibuddy.ai_usage")

OPERATIONS = frozenset({"answer", "summary", "query_embedding", "document_embedding"})


async def record_usage(
    sb: Any,
    *,
    operation: str,
    model: str,
    request_count: int = 1,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    if operation not in OPERATIONS:
        raise ValueError(f"unknown AI usage operation: {operation}")
    try:
        await sb.insert_service(
            "ai_usage_events",
            [
                {
                    "id": str(uuid4()),
                    "operation": operation,
                    "model": model or "unknown",
                    "request_count": request_count,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                }
            ],
        )
    except Exception:  # noqa: BLE001 - metering must never fail the answer, summary or embedding it describes
        logger.warning("AI usage metadata could not be recorded (%s)", operation)


def embedding_model_name(ai: Any) -> str:
    return str(getattr(ai, "_embedding_model", "") or "unknown")
