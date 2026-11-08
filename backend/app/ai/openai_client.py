from typing import Any

import httpx

EMBEDDING_DIMENSIONS = 1536
EMBEDDING_BATCH_SIZE = 96


class OpenAIError(Exception):
    pass


class OpenAIClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        embedding_model: str,
        chat_model: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._embedding_model = embedding_model
        self._chat_model = chat_model
        self._transport = transport

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=60.0,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._http() as client:
                response = await client.post(f"{self._base_url}{path}", json=body)
        except httpx.HTTPError as exc:
            raise OpenAIError("OpenAI request failed") from exc
        if response.status_code >= 400:
            raise OpenAIError(f"OpenAI returned HTTP {response.status_code}")
        return response.json()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[start : start + EMBEDDING_BATCH_SIZE]
            payload = await self._post("/embeddings", {"model": self._embedding_model, "input": batch})
            items = sorted(payload["data"], key=lambda item: item["index"])
            for item in items:
                vector = item["embedding"]
                if len(vector) != EMBEDDING_DIMENSIONS:
                    raise OpenAIError(f"Embedding has {len(vector)} dimensions, expected {EMBEDDING_DIMENSIONS}")
                vectors.append(vector)
        if len(vectors) != len(texts):
            raise OpenAIError("Embedding count does not match input count")
        return vectors

    async def complete(self, system: str, user: str) -> str:
        payload = await self._post(
            "/chat/completions",
            {
                "model": self._chat_model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        try:
            return payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenAIError("OpenAI response had no message content") from exc
