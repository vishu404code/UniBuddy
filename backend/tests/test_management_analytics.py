"""Management analytics: role gate, aggregate-only output, and Gemini usage recording.

No real Management account is needed. Fixtures stand in for the database profiles, and
the role comes from those profiles, never from the request.
"""

import uuid
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.ai.gemini_client import GeminiClient, GenerationUsage
from app.config import settings
from app.main import app
from app.middleware.auth import get_profile_repository, get_token_verifier
from app.services.chat import _UsageRecordingGenerator
from app.services.providers import get_data_client
from tests.conftest import FakeProfileRepository, make_profile
from tests.fakes import FakeDataClient

API = settings.api_v1_prefix
CAMPUS = str(uuid4())
IDS = {
    "student": str(uuid4()),
    "faculty": str(uuid4()),
    "authority": str(uuid4()),
    "management": str(uuid4()),
}


class _Verifier:
    def verify(self, token):
        return uuid.UUID(token)


def _auth(user_id):
    return {"Authorization": f"Bearer {user_id}"}


def _analytics_payload():
    days = [{"day": "2026-11-09", "count": 2}, {"day": "2026-11-10", "count": 0}]
    return {
        "questions_total": 39,
        "questions_by_day": days,
        "tickets_by_day": days,
        "gemini": {
            "operation": "answer",
            "first_recorded_at": None,
            "last_recorded_at": None,
            "rows_recorded": 0,
            "requests": 0,
            "rows_with_input_tokens": 0,
            "rows_with_output_tokens": 0,
            "input_tokens": None,
            "output_tokens": None,
            "models": [],
        },
        "ticket_totals": {
            "total_tickets": 6, "resolved_tickets": 4, "resolution_rate": 0.6667,
            "avg_first_response_hours": 2.5, "campuses": [], "departments": [],
            "generated_at": "2026-11-10T10:00:00+00:00",
        },
        "generated_at": "2026-11-10T10:00:00+00:00",
    }


@pytest.fixture
def client():
    profiles = {
        IDS["student"]: make_profile(IDS["student"], role="student", campus_id=CAMPUS),
        IDS["faculty"]: make_profile(IDS["faculty"], role="faculty", campus_id=CAMPUS),
        IDS["authority"]: make_profile(IDS["authority"], role="authority", campus_id=CAMPUS),
        IDS["management"]: make_profile(IDS["management"], role="management", campus_id=CAMPUS),
    }
    sb = FakeDataClient()
    sb.rpc_responses["management_activity_stats"] = _analytics_payload()
    sb.rpc_responses["management_ticket_stats"] = _analytics_payload()["ticket_totals"]
    app.dependency_overrides[get_token_verifier] = lambda: _Verifier()
    app.dependency_overrides[get_profile_repository] = lambda: FakeProfileRepository(profiles)
    app.dependency_overrides[get_data_client] = lambda: sb
    try:
        yield TestClient(app), sb
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("role", ["student", "faculty", "authority"])
def test_only_management_can_read_analytics(client, role):
    test_client, _ = client
    response = test_client.get(f"{API}/management/analytics", headers=_auth(IDS[role]))
    assert response.status_code == 403


def test_anonymous_request_is_refused(client):
    test_client, _ = client
    assert test_client.get(f"{API}/management/analytics").status_code in (401, 403)


def test_management_gets_aggregates_without_personal_data(client):
    test_client, _ = client
    response = test_client.get(f"{API}/management/analytics", headers=_auth(IDS["management"]))
    assert response.status_code == 200
    body = response.json()
    assert body["questions_total"] == 39
    assert len(body["questions_by_day"]) == 2
    assert body["ticket_totals"]["total_tickets"] == 6
    assert body["gemini"]["input_tokens"] is None  # nothing recorded: reported as unavailable, not zero
    assert "@" not in response.text
    for forbidden in ("email", "student_id", "user_id", "\"content\"", "question_text", "full_name"):
        assert forbidden not in response.text


def test_browser_cannot_choose_the_management_role(client):
    test_client, _ = client
    # A student token with a role claim in the request body or query string still gets the student role.
    response = test_client.get(
        f"{API}/management/analytics?role=management", headers=_auth(IDS["student"])
    )
    assert response.status_code == 403


class _CompletionModels:
    def __init__(self, response):
        self._response = response

    async def generate_content(self, **kwargs):
        return self._response


class _FakeGenai:
    def __init__(self, response):
        self.aio = SimpleNamespace(models=_CompletionModels(response))


@pytest.mark.asyncio
async def test_gemini_usage_metadata_is_read_when_returned():
    response = SimpleNamespace(
        text=" Pay in week two. ",
        usage_metadata=SimpleNamespace(prompt_token_count=120, candidates_token_count=17),
    )
    gemini = GeminiClient("unused", "emb", "chat-model", client=_FakeGenai(response))
    text, usage = await gemini.complete_with_usage("system", "user")
    assert text == "Pay in week two."
    assert usage == GenerationUsage(model="chat-model", input_tokens=120, output_tokens=17)


@pytest.mark.asyncio
async def test_missing_usage_metadata_is_recorded_as_unknown_not_estimated():
    response = SimpleNamespace(text="An answer", usage_metadata=None)
    gemini = GeminiClient("unused", "emb", "chat-model", client=_FakeGenai(response))
    _, usage = await gemini.complete_with_usage("system", "user")
    assert usage.input_tokens is None and usage.output_tokens is None


class _UsageAI:
    def __init__(self, usage, text="answer text"):
        self._usage = usage
        self._text = text

    async def complete_with_usage(self, system, user):
        return self._text, self._usage


@pytest.mark.asyncio
async def test_usage_row_holds_only_metadata():
    sb = FakeDataClient()
    usage = GenerationUsage(model="chat-model", input_tokens=120, output_tokens=17)
    text = await _UsageRecordingGenerator(_UsageAI(usage), sb).complete("SECRET SYSTEM", "private student question")
    assert text == "answer text"
    [row] = sb.tables["ai_usage_events"]
    assert set(row) - {"created_at"} == {"id", "operation", "model", "request_count", "input_tokens", "output_tokens"}
    assert row["operation"] == "answer" and row["model"] == "chat-model"
    assert row["request_count"] == 1 and row["input_tokens"] == 120 and row["output_tokens"] == 17
    assert "private student question" not in repr(sb.tables["ai_usage_events"])


@pytest.mark.asyncio
async def test_failed_usage_write_never_fails_the_answer():
    sb = FakeDataClient()

    async def broken_insert(table, rows):
        raise RuntimeError("database unavailable")

    sb.insert_service = broken_insert
    usage = GenerationUsage(model="chat-model", input_tokens=None, output_tokens=None)
    assert await _UsageRecordingGenerator(_UsageAI(usage), sb).complete("s", "u") == "answer text"


@pytest.mark.asyncio
async def test_generators_without_usage_pass_through_and_record_nothing():
    class Plain:
        async def complete(self, system, user):
            return "plain"

    sb = FakeDataClient()
    assert await _UsageRecordingGenerator(Plain(), sb).complete("s", "u") == "plain"
    assert sb.tables["ai_usage_events"] == []
