from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from app.ai.gemini_client import EMBEDDING_DIMENSIONS, AIServiceError, GeminiClient
from app.config import Settings

KEY = "test-only-key"


class FakeModels:
    """Stands in for client.aio.models. Records each call; never contacts Google."""

    def __init__(self, reply="", embed_error=None, generate_error=None):
        self.reply = reply
        self.embed_error = embed_error
        self.generate_error = generate_error
        self.embed_calls: list[dict] = []
        self.generate_calls: list[dict] = []

    async def embed_content(self, *, model, contents, config):
        self.embed_calls.append({"model": model, "contents": list(contents), "config": config})
        if self.embed_error:
            raise self.embed_error
        return SimpleNamespace(
            embeddings=[
                SimpleNamespace(values=[float(i)] * EMBEDDING_DIMENSIONS) for i, _ in enumerate(contents)
            ]
        )

    async def generate_content(self, *, model, contents, config):
        self.generate_calls.append({"model": model, "contents": contents, "config": config})
        if self.generate_error:
            raise self.generate_error
        return SimpleNamespace(text=self.reply)


def _client(models: FakeModels) -> GeminiClient:
    fake_sdk = SimpleNamespace(aio=SimpleNamespace(models=models))
    return GeminiClient(
        api_key=KEY,
        embedding_model="gemini-embedding-001",
        chat_model="gemini-test",
        client=fake_sdk,
    )


@pytest.mark.asyncio
async def test_documents_use_document_task_type_and_fixed_dimensions():
    models = FakeModels()

    vectors = await _client(models).embed_documents(["a", "b"])

    call = models.embed_calls[0]
    assert call["model"] == "gemini-embedding-001"
    assert call["config"].task_type == "RETRIEVAL_DOCUMENT"
    assert call["config"].output_dimensionality == EMBEDDING_DIMENSIONS
    assert call["contents"] == ["a", "b"]
    assert len(vectors) == 2 and all(len(v) == EMBEDDING_DIMENSIONS for v in vectors)


@pytest.mark.asyncio
async def test_questions_use_query_task_type_so_they_share_the_document_space():
    models = FakeModels()

    vector = await _client(models).embed_query("When are fees due?")

    call = models.embed_calls[0]
    assert call["config"].task_type == "RETRIEVAL_QUERY"
    assert call["config"].output_dimensionality == EMBEDDING_DIMENSIONS
    assert len(vector) == EMBEDDING_DIMENSIONS


@pytest.mark.asyncio
async def test_large_documents_are_embedded_in_batches():
    models = FakeModels()
    texts = [f"chunk {i}" for i in range(250)]

    vectors = await _client(models).embed_documents(texts)

    assert [len(c["contents"]) for c in models.embed_calls] == [100, 100, 50]
    assert len(vectors) == 250


@pytest.mark.asyncio
async def test_wrong_dimension_is_rejected():
    class ShortModels(FakeModels):
        async def embed_content(self, *, model, contents, config):
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1, 0.2])])

    with pytest.raises(AIServiceError, match="dimensions"):
        await _client(ShortModels()).embed_documents(["a"])


@pytest.mark.asyncio
async def test_missing_embeddings_are_rejected():
    class EmptyModels(FakeModels):
        async def embed_content(self, *, model, contents, config):
            return SimpleNamespace(embeddings=[])

    with pytest.raises(AIServiceError, match="count"):
        await _client(EmptyModels()).embed_documents(["a"])


@pytest.mark.asyncio
async def test_api_errors_are_reduced_to_status_code_without_leaking_the_message():
    error = genai_errors.APIError(429, {"error": {"message": "quota for sk-leaked", "status": "RESOURCE_EXHAUSTED"}})

    with pytest.raises(AIServiceError) as info:
        await _client(FakeModels(embed_error=error)).embed_documents(["a"])

    assert "429" in str(info.value)
    assert "sk-leaked" not in str(info.value)
    assert KEY not in str(info.value)


@pytest.mark.asyncio
async def test_transport_failures_become_a_safe_service_error():
    with pytest.raises(AIServiceError, match="request failed"):
        await _client(FakeModels(embed_error=ConnectionError("network down"))).embed_documents(["a"])


@pytest.mark.asyncio
async def test_complete_sends_system_instruction_at_zero_temperature():
    models = FakeModels(reply="  Pay in week two [1].  ")

    text = await _client(models).complete("system text", "user text")

    call = models.generate_calls[0]
    assert call["model"] == "gemini-test"
    assert call["contents"] == "user text"
    assert call["config"].system_instruction == "system text"
    assert call["config"].temperature == 0
    assert text == "Pay in week two [1]."


@pytest.mark.asyncio
async def test_empty_answer_is_returned_as_empty_text_so_rag_can_abstain():
    assert await _client(FakeModels(reply=None)).complete("s", "u") == ""


def test_default_models_and_no_openai_settings():
    settings = Settings(_env_file=None)

    assert settings.gemini_embedding_model == "gemini-embedding-001"
    assert settings.gemini_chat_model == "gemini-2.5-flash"
    assert settings.gemini_api_key is None
    assert not hasattr(settings, "openai_api_key")
