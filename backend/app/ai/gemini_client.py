"""Gemini embeddings and answers through Google's GenAI SDK. Server-side only.

Document chunks and questions use the same embedding model and dimension, so their
vectors live in one space. Documents use the RETRIEVAL_DOCUMENT task type and questions
use RETRIEVAL_QUERY, which is how Gemini's retrieval embeddings are meant to be used.
"""

import asyncio
import logging
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

logger = logging.getLogger("unibuddy.gemini")

# Must match the vector(1536) column in document_chunks.
EMBEDDING_DIMENSIONS = 1536
EMBEDDING_BATCH_SIZE = 100
DOCUMENT_TASK = "RETRIEVAL_DOCUMENT"
QUERY_TASK = "RETRIEVAL_QUERY"
FALLBACK_CHAT_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]


class AIServiceError(Exception):
    """A safe, key-free reason an AI call failed. It never contains the API key or request content."""


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        embedding_model: str,
        chat_model: str,
        client: Any | None = None,
    ):
        self._embedding_model = embedding_model
        self._chat_model = chat_model
        # `client` lets tests inject a fake; production builds the SDK client from the key.
        self._client = client if client is not None else genai.Client(api_key=api_key)

    async def _call(self, label: str, request) -> Any:
        last_exc = None
        for attempt in range(3):
            try:
                return await request()
            except genai_errors.APIError as exc:
                last_exc = exc
                if exc.code == 429 and attempt < 2:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                raise AIServiceError(f"Gemini {label} returned HTTP {exc.code}") from exc
            except Exception as exc:
                last_exc = exc
                if attempt < 2 and "timeout" in str(exc).lower():
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise AIServiceError(f"Gemini {label} request failed") from exc
        raise AIServiceError(f"Gemini {label} request failed after retries") from last_exc

    async def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[start : start + EMBEDDING_BATCH_SIZE]

            async def request(batch=batch):
                return await self._client.aio.models.embed_content(
                    model=self._embedding_model,
                    contents=batch,
                    config=types.EmbedContentConfig(
                        task_type=task_type,
                        output_dimensionality=EMBEDDING_DIMENSIONS,
                    ),
                )

            response = await self._call("embedding", request)
            embeddings = list(response.embeddings or [])
            if len(embeddings) != len(batch):
                raise AIServiceError("Embedding count does not match input count")
            for item in embeddings:
                values = [float(v) for v in (item.values or [])]
                if len(values) != EMBEDDING_DIMENSIONS:
                    raise AIServiceError(
                        f"Embedding has {len(values)} dimensions, expected {EMBEDDING_DIMENSIONS}"
                    )
                vectors.append(values)
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts, DOCUMENT_TASK)

    async def embed_query(self, text: str) -> list[float]:
        [vector] = await self._embed([text], QUERY_TASK)
        return vector

    async def complete(self, system: str, user: str) -> str:
        models_to_try = [self._chat_model] + [m for m in FALLBACK_CHAT_MODELS if m != self._chat_model]
        last_error = None
        for model_name in models_to_try:
            try:
                async def request():
                    return await self._client.aio.models.generate_content(
                        model=model_name,
                        contents=user,
                        config=types.GenerateContentConfig(system_instruction=system, temperature=0),
                    )

                response = await self._call("answer", request)
                return (response.text or "").strip()
            except AIServiceError as exc:
                last_error = exc
                if "HTTP 404" in str(exc):
                    logger.warning("Gemini model %s not available, trying fallback", model_name)
                    continue
                raise
        raise last_error or AIServiceError("Gemini chat completion failed on all candidate models")

    async def test_connection(self) -> dict[str, Any]:
        """Diagnostic to verify Gemini API connectivity without exposing the API key."""
        try:
            embed_res = await self.embed_query("test connectivity")
            chat_res = await self.complete("You are a test system.", "Reply with 'PONG'")
            return {
                "status": "connected",
                "embedding_model": self._embedding_model,
                "embedding_dimensions": len(embed_res),
                "chat_model": self._chat_model,
                "sample_response": chat_res[:50],
            }
        except Exception as exc:
            return {
                "status": "error",
                "embedding_model": self._embedding_model,
                "chat_model": self._chat_model,
                "error": str(exc),
            }
