import asyncio
import json
from uuid import UUID

import httpx
import pytest

from app.repositories.profiles import ProfileLookupError, ProfileRepository

SUPABASE_URL = "https://test-project.supabase.co"
SECRET_KEY = "sb_secret_test-only-value"
USER_ID = UUID("99999999-9999-9999-9999-999999999999")


def _repo(handler):
    return ProfileRepository(SUPABASE_URL, SECRET_KEY, transport=httpx.MockTransport(handler))


def test_lookup_sends_secret_key_in_apikey_only_and_filters_by_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["apikey"] = request.headers["apikey"]
        seen["has_authorization"] = "authorization" in request.headers
        return httpx.Response(200, json=[])

    asyncio.run(_repo(handler).get_by_id(USER_ID))

    assert seen["url"].startswith(f"{SUPABASE_URL}/rest/v1/profiles?")
    assert f"id=eq.{USER_ID}" in seen["url"]
    assert seen["apikey"] == SECRET_KEY
    assert seen["has_authorization"] is False


def test_missing_profile_returns_none():
    repo = _repo(lambda request: httpx.Response(200, json=[]))

    assert asyncio.run(repo.get_by_id(USER_ID)) is None


def test_existing_profile_is_parsed():
    row = {
        "id": str(USER_ID),
        "email": "student@example.edu",
        "full_name": "Asha",
        "role": "student",
        "campus_id": None,
        "department_id": None,
    }
    repo = _repo(lambda request: httpx.Response(200, json=[row]))

    profile = asyncio.run(repo.get_by_id(USER_ID))

    assert profile.id == USER_ID
    assert profile.role == "student"


def test_non_200_response_raises():
    repo = _repo(lambda request: httpx.Response(500, json={"message": "boom"}))

    with pytest.raises(ProfileLookupError):
        asyncio.run(repo.get_by_id(USER_ID))


def test_network_failure_raises():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("unreachable")

    with pytest.raises(ProfileLookupError):
        asyncio.run(_repo(handler).get_by_id(USER_ID))
