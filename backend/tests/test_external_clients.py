import json

import httpx
import pytest

from app.ai.openai_client import EMBEDDING_DIMENSIONS, OpenAIClient, OpenAIError
from app.services.supabase_client import SupabaseClient, SupabaseError

SUPABASE = "https://test-project.supabase.co"
SECRET = "sb_secret_test-only-value"
PUBLISHABLE = "sb_publishable_test-only-value"
USER_TOKEN = "eyJ.test.user-token"


def _openai(handler):
    return OpenAIClient(
        api_key="sk-test-only",
        base_url="https://api.openai.test/v1",
        embedding_model="text-embedding-3-small",
        chat_model="gpt-test",
        transport=httpx.MockTransport(handler),
    )


def _supabase(handler):
    return SupabaseClient(SUPABASE, SECRET, PUBLISHABLE, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_embed_returns_vectors_in_input_order_and_checks_dimensions():
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "text-embedding-3-small"
        data = [
            {"index": i, "embedding": [float(i)] * EMBEDDING_DIMENSIONS}
            for i in reversed(range(len(body["input"])))
        ]
        return httpx.Response(200, json={"data": data})

    vectors = await _openai(handler).embed(["a", "b"])

    assert vectors[0][0] == 0.0 and vectors[1][0] == 1.0


@pytest.mark.asyncio
async def test_embed_rejects_wrong_dimension():
    def handler(request):
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})

    with pytest.raises(OpenAIError, match="dimensions"):
        await _openai(handler).embed(["a"])


@pytest.mark.asyncio
async def test_embed_maps_http_errors_without_leaking_body():
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "bad key sk-secret"}})

    with pytest.raises(OpenAIError) as info:
        await _openai(handler).embed(["a"])
    assert "sk-secret" not in str(info.value)
    assert "401" in str(info.value)


@pytest.mark.asyncio
async def test_complete_sends_system_and_user_messages_at_zero_temperature():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "Pay in week two [1]."}}]})

    text = await _openai(handler).complete("system text", "user text")

    assert text == "Pay in week two [1]."
    assert seen["body"]["temperature"] == 0
    assert seen["body"]["messages"][0] == {"role": "system", "content": "system text"}
    assert seen["auth"] == "Bearer sk-test-only"


@pytest.mark.asyncio
async def test_service_calls_send_secret_key_only_in_apikey():
    seen = {}

    def handler(request):
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json=[])

    await _supabase(handler).select_service("profiles", {"id": "eq.x"})

    assert seen["headers"]["apikey"] == SECRET
    assert "authorization" not in seen["headers"]


@pytest.mark.asyncio
async def test_user_calls_use_publishable_key_and_user_token_never_secret():
    seen = {}

    def handler(request):
        seen["apikey"] = request.headers["apikey"]
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json=[])

    await _supabase(handler).select_as_user(USER_TOKEN, "documents", {"select": "*"})

    assert seen["apikey"] == PUBLISHABLE
    assert seen["apikey"] != SECRET
    assert seen["auth"] == f"Bearer {USER_TOKEN}"


@pytest.mark.asyncio
async def test_user_calls_refuse_to_run_without_publishable_key():
    client = SupabaseClient(SUPABASE, SECRET, None, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))

    with pytest.raises(SupabaseError) as info:
        await client.select_as_user(USER_TOKEN, "documents", {})
    assert info.value.status_code == 503


@pytest.mark.asyncio
async def test_rpc_posts_arguments_to_the_named_function_as_the_user():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=[{"title": "Fee Policy"}])

    rows = await _supabase(handler).rpc_as_user(USER_TOKEN, "match_document_chunks", {"match_count": 5})

    assert seen["url"] == f"{SUPABASE}/rest/v1/rpc/match_document_chunks"
    assert seen["auth"] == f"Bearer {USER_TOKEN}"
    assert seen["body"] == {"match_count": 5}
    assert rows == [{"title": "Fee Policy"}]


@pytest.mark.asyncio
async def test_select_all_pages_past_the_row_cap():
    pages = {"0": [{"n": i} for i in range(1000)], "1000": [{"n": 1000}, {"n": 1001}]}

    def handler(request):
        return httpx.Response(200, json=pages[request.url.params["offset"]])

    rows = await _supabase(handler).select_all_service("tickets", {"select": "n"}, page_size=1000)

    assert len(rows) == 1002


@pytest.mark.asyncio
async def test_storage_upload_uses_secret_key_and_upsert_disabled():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = request.content
        return httpx.Response(200, json={"Key": "documents/x.pdf"})

    await _supabase(handler).upload_object("documents", "campus/x.pdf", b"%PDF-1.4 bytes", "application/pdf")

    assert seen["url"] == f"{SUPABASE}/storage/v1/object/documents/campus/x.pdf"
    assert seen["headers"]["apikey"] == SECRET
    assert seen["headers"]["x-upsert"] == "false"
    assert seen["body"] == b"%PDF-1.4 bytes"


@pytest.mark.asyncio
async def test_update_returns_representation_so_callers_can_detect_no_match():
    def handler(request):
        assert request.headers["prefer"] == "return=representation"
        return httpx.Response(200, json=[])

    assert await _supabase(handler).update_service("tickets", {"id": "eq.x"}, {"status": "assigned"}) == []


@pytest.mark.asyncio
async def test_paged_read_as_user_requests_exact_count_and_parses_total():
    seen = {}

    def handler(request):
        seen["prefer"] = request.headers["prefer"]
        seen["limit"], seen["offset"] = request.url.params["limit"], request.url.params["offset"]
        seen["apikey"] = request.headers["apikey"]
        return httpx.Response(200, json=[{"id": "1"}], headers={"content-range": "20-20/57"})

    rows, total = await _supabase(handler).select_page_as_user(USER_TOKEN, "tickets", {}, limit=1, offset=20)

    assert seen["prefer"] == "count=exact"
    assert (seen["limit"], seen["offset"]) == ("1", "20")
    assert seen["apikey"] == PUBLISHABLE
    assert rows == [{"id": "1"}] and total == 57


@pytest.mark.asyncio
async def test_count_as_user_uses_zero_limit_and_returns_total():
    def handler(request):
        assert request.url.params["limit"] == "0"
        return httpx.Response(200, json=[], headers={"content-range": "*/12"})

    assert await _supabase(handler).count_as_user(USER_TOKEN, "messages", {"role": "eq.user"}) == 12


@pytest.mark.asyncio
async def test_download_uses_the_secret_key_and_returns_bytes():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["apikey"] = request.headers["apikey"]
        return httpx.Response(200, content=b"%PDF-1.4 data")

    assert await _supabase(handler).download_object("documents", "campus/a.pdf") == b"%PDF-1.4 data"
    assert seen["url"] == f"{SUPABASE}/storage/v1/object/documents/campus/a.pdf"
    assert seen["apikey"] == SECRET


@pytest.mark.asyncio
async def test_storage_delete_and_row_delete_use_the_secret_key():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url), request.headers["apikey"]))
        return httpx.Response(200, json={})

    client = _supabase(handler)
    await client.delete_object("documents", "campus/a.pdf")
    await client.delete_service("document_chunks", {"document_id": "eq.x"})

    assert seen[0][0] == "DELETE" and "/storage/v1/object/documents/campus/a.pdf" in seen[0][1]
    assert seen[1][0] == "DELETE" and "/rest/v1/document_chunks" in seen[1][1]
    assert all(key == SECRET for _, _, key in seen)


@pytest.mark.asyncio
async def test_service_rpc_posts_to_the_function_with_the_secret_key():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["apikey"] = request.headers["apikey"]
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={"total_tickets": 3})

    result = await _supabase(handler).rpc_service("management_ticket_stats", {})

    assert seen["url"] == f"{SUPABASE}/rest/v1/rpc/management_ticket_stats"
    assert seen["apikey"] == SECRET
    assert seen["authorization"] is None
    assert result == {"total_tickets": 3}
