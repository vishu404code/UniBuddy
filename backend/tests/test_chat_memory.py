"""Personal chat memory: ranking by last use, gradual pruning, six-month-old useful memories, correction and
deletion, cleanup failure, cross-student isolation, the flag-off path, and how memory may reach an answer.

Fixtures only: every student, memory and time here is created in this file. Times are fixed, so results do
not depend on the clock. The database is the in-memory fake; RLS is simulated by the `visible` rule (a row is
readable by its owner only). No network calls and no AI service: the model is a fake.

Every test runs with CHAT_MEMORY_CONTEXT_ENABLED on unless it says otherwise (see _flag_on below)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.ai.rag import Evidence
from app.config import settings
from app.routes import chat as chat_routes
from app.schemas.chat import AskRequest, MemoryPatch
from app.services import chat_memory as cm
from app.services.chat import ask_question
from app.services.chat_retention import recent_summaries, tidy_student_chats, tidy_student_chats_safely
from app.services.documents import DocumentError, DocumentNotFound
from app.services.errors import DataServiceError
from tests.conftest import make_profile
from tests.fakes import FakeAI, FakeDataClient

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
SECRET_TEXT = "my password is hunter2-fixture and mail a.b@example.edu"


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "chat_memory_context_enabled", True)


class NoTouchClient:
    """Records every database method the code tries to use. Services catch errors broadly, so a test asserts
    on `touched` rather than on an exception: the flag-off path must leave `touched` empty."""

    def __init__(self):
        self.touched = []

    def __getattr__(self, name):
        self.touched.append(name)
        raise AssertionError(f"database touched while memory is off: {name}")


def _days_ago(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat()


def _student(sb, name="Fixture Student"):
    student = make_profile(str(uuid4()), role="student", campus_id=str(uuid4()))
    sb.tables["profiles"].append({"id": str(student.id), "email": f"{student.id}@example.edu", "full_name": name,
                                  "role": "student", "campus_id": str(student.campus_id)})
    return student


def _memory(sb, owner, *, days_old=30, used_days_ago=None, use_count=0, importance="normal",
            text="fixture memory", corrected=None):
    """days_old: when the chat was last active. used_days_ago: when the note last helped an answer."""
    memory_id = str(uuid4())
    sb.tables["chat_summaries"].append({
        "id": memory_id, "user_id": str(owner.id), "conversation_id": None,
        "batch_key": uuid4().hex + uuid4().hex, "message_count": 1,
        "first_message_at": _days_ago(days_old), "last_message_at": _days_ago(days_old),
        "summary": text, "created_at": _days_ago(days_old), "importance": importance,
        "use_count": use_count,
        "last_used_at": _days_ago(used_days_ago) if used_days_ago is not None else None,
        "corrected_at": corrected,
    })
    return memory_id


def _rls_db():
    """Simulates the owner-only policy on chat_summaries for reads made as a student."""
    return FakeDataClient(visible=lambda token, table, row: table != "chat_summaries" or row.get("user_id") == token)


def _fresh_padding(sb, owner, count=cm.MIN_KEEP):
    """Recent unused notes, so the floor of MIN_KEEP never lets the stale note under test be ignored."""
    for _ in range(count):
        _memory(sb, owner, days_old=1)


def _pruned_summaries(sb):
    """The texts of the notes one pruning run would remove."""
    return [c["summary"] for c in cm.prune_candidates(sb.tables["chat_summaries"], NOW)]


# --- Ranking by last use --------------------------------------------------------------------------

def test_a_useful_six_month_old_memory_outranks_a_fresh_unused_one():
    sb = FakeDataClient()
    owner = _student(sb)
    fresh_unused = _memory(sb, owner, days_old=2, text="fresh, never used")
    old_useful = _memory(sb, owner, days_old=400, used_days_ago=182, use_count=3,
                         text="used three times, last used six months ago")

    ranked = cm.rank_memories(sb.tables["chat_summaries"], NOW, limit=2)

    assert [r["id"] for r in ranked] == [old_useful, fresh_unused]


def test_a_note_used_recently_outranks_an_equally_old_unused_note():
    sb = FakeDataClient()
    owner = _student(sb)
    unused = _memory(sb, owner, days_old=400, text="unused, over a year old")
    used = _memory(sb, owner, days_old=400, used_days_ago=1, use_count=1, text="used yesterday")
    rows = {r["id"]: r for r in sb.tables["chat_summaries"]}

    assert cm.memory_score(rows[used], NOW) > cm.memory_score(rows[unused], NOW)
    ranked = cm.rank_memories(sb.tables["chat_summaries"], NOW, limit=2)
    assert [r["id"] for r in ranked] == [used, unused]


def test_pinned_memories_rank_first_whatever_their_score():
    sb = FakeDataClient()
    owner = _student(sb)
    _memory(sb, owner, days_old=1, used_days_ago=1, use_count=3, text="recent and busy")
    pinned = _memory(sb, owner, days_old=900, importance="pinned", text="pinned from long ago")

    ranked = cm.rank_memories(sb.tables["chat_summaries"], NOW, limit=2)

    assert ranked[0]["id"] == pinned


def test_important_adds_exactly_the_importance_bonus():
    sb = FakeDataClient()
    owner = _student(sb)
    plain = _memory(sb, owner, days_old=10)
    important = _memory(sb, owner, days_old=10, importance="important")
    rows = {r["id"]: r for r in sb.tables["chat_summaries"]}

    difference = cm.memory_score(rows[important], NOW) - cm.memory_score(rows[plain], NOW)
    assert difference == pytest.approx(cm.IMPORTANT_BONUS)


# --- Gradual pruning ------------------------------------------------------------------------------

@pytest.mark.parametrize("idle, expected", [(280, []), (310, ["unused note"])])
def test_an_unused_note_is_kept_at_280_idle_days_and_pruned_at_310(idle, expected):
    sb = FakeDataClient()
    owner = _student(sb)
    _fresh_padding(sb, owner)
    _memory(sb, owner, days_old=idle, text="unused note")

    assert _pruned_summaries(sb) == expected


def test_an_unused_note_under_the_minimum_age_is_never_pruned():
    sb = FakeDataClient()
    owner = _student(sb)
    _fresh_padding(sb, owner)
    _memory(sb, owner, days_old=60, text="unused, 60 days")

    assert cm.prune_candidates(sb.tables["chat_summaries"], NOW) == []


def test_a_note_used_once_stays_while_its_last_use_is_recent():
    sb = FakeDataClient()
    owner = _student(sb)
    _fresh_padding(sb, owner)
    _memory(sb, owner, days_old=900, used_days_ago=340, use_count=1, text="used once, 340 days ago")

    assert cm.prune_candidates(sb.tables["chat_summaries"], NOW) == []


def test_a_note_used_once_is_pruned_after_long_disuse():
    """Used once is not kept forever: once the last use is long enough ago, it is removed."""
    sb = FakeDataClient()
    owner = _student(sb)
    _fresh_padding(sb, owner)
    _memory(sb, owner, days_old=900, used_days_ago=600, use_count=1, text="used once, 600 days ago")

    assert _pruned_summaries(sb) == ["used once, 600 days ago"]


def test_a_note_used_three_times_is_pruned_after_two_years_without_use():
    sb = FakeDataClient()
    owner = _student(sb)
    _fresh_padding(sb, owner)
    _memory(sb, owner, days_old=900, used_days_ago=900, use_count=3, text="used three times, 900 days ago")

    assert _pruned_summaries(sb) == ["used three times, 900 days ago"]


def test_a_six_month_old_useful_memory_survives_a_pruning_run():
    sb = FakeDataClient()
    owner = _student(sb)
    _fresh_padding(sb, owner)
    useful = _memory(sb, owner, days_old=400, used_days_ago=182, use_count=3,
                     text="useful for answers, last used six months ago")

    result = cm.prune_candidates(sb.tables["chat_summaries"], NOW)

    assert all(c["id"] != useful for c in result)


def test_a_recent_use_keeps_a_note_whose_chat_is_old():
    sb = FakeDataClient()
    owner = _student(sb)
    _fresh_padding(sb, owner)
    _memory(sb, owner, days_old=800, used_days_ago=2, use_count=1, text="old chat, used last week")

    assert cm.prune_candidates(sb.tables["chat_summaries"], NOW) == []


@pytest.mark.parametrize("importance", ["important", "pinned"])
def test_important_and_pinned_memories_are_never_pruned(importance):
    sb = FakeDataClient()
    owner = _student(sb)
    _fresh_padding(sb, owner)
    _memory(sb, owner, days_old=800, importance=importance)

    assert cm.prune_candidates(sb.tables["chat_summaries"], NOW) == []


def test_pruning_is_bounded_per_run_and_keeps_a_floor():
    sb = FakeDataClient()
    owner = _student(sb)
    for _ in range(cm.MIN_KEEP + 30):
        _memory(sb, owner, days_old=800)

    candidates = cm.prune_candidates(sb.tables["chat_summaries"], NOW)

    assert len(candidates) == cm.MAX_PRUNE_PER_RUN
    assert len(sb.tables["chat_summaries"]) - len(candidates) >= cm.MIN_KEEP


def test_a_student_with_few_memories_keeps_them_all():
    sb = FakeDataClient()
    owner = _student(sb)
    for _ in range(cm.MIN_KEEP):
        _memory(sb, owner, days_old=800)

    assert cm.prune_candidates(sb.tables["chat_summaries"], NOW) == []


@pytest.mark.asyncio
async def test_a_pruning_run_removes_only_stale_notes_and_only_for_its_owner():
    sb = _rls_db()
    alice, bob = _student(sb, "Alice"), _student(sb, "Bob")
    _fresh_padding(sb, alice)
    stale = _memory(sb, alice, days_old=800, text="alice stale")
    bobs_stale = _memory(sb, bob, days_old=800, text="bob stale")

    result = await cm.prune_student_memories(sb=sb, user=alice, now=NOW)

    assert result.status == "pruned" and result.removed == 1
    remaining = {r["id"] for r in sb.tables["chat_summaries"]}
    assert stale not in remaining
    assert bobs_stale in remaining


# --- Correction and deletion ------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_owner_corrects_the_text_and_the_redacted_text_is_stored():
    sb = _rls_db()
    owner = _student(sb)
    memory_id = _memory(sb, owner, text="old text")

    row = await cm.correct_memory(sb=sb, user=owner, memory_id=memory_id,
                                  text=f"Corrected: prefers evening classes. {SECRET_TEXT}", now=NOW)

    assert "Corrected" in row["summary"]
    assert "hunter2-fixture" not in row["summary"]
    assert "a.b@example.edu" not in row["summary"]
    assert row["corrected_at"] is not None


@pytest.mark.asyncio
async def test_another_student_cannot_correct_or_delete_a_memory():
    sb = _rls_db()
    owner, intruder = _student(sb, "Owner"), _student(sb, "Intruder")
    memory_id = _memory(sb, owner, text="owner's note")

    with pytest.raises(DocumentNotFound):
        await cm.correct_memory(sb=sb, user=intruder, memory_id=memory_id, text="changed")
    with pytest.raises(DocumentNotFound):
        await cm.delete_memory(sb=sb, user=intruder, memory_id=memory_id)

    assert [r["summary"] for r in sb.tables["chat_summaries"]] == ["owner's note"]


@pytest.mark.asyncio
async def test_the_owner_deletes_a_memory_and_it_is_gone():
    sb = _rls_db()
    owner = _student(sb)
    memory_id = _memory(sb, owner)

    await cm.delete_memory(sb=sb, user=owner, memory_id=memory_id)

    assert sb.tables["chat_summaries"] == []


@pytest.mark.asyncio
async def test_an_empty_correction_and_a_bad_importance_value_are_refused():
    sb = _rls_db()
    owner = _student(sb)
    memory_id = _memory(sb, owner)

    with pytest.raises(DocumentError):
        await cm.correct_memory(sb=sb, user=owner, memory_id=memory_id, text="   ")
    with pytest.raises(DocumentError):
        await cm.correct_memory(sb=sb, user=owner, memory_id=memory_id, importance="forever")


@pytest.mark.asyncio
async def test_importance_can_be_set_by_the_owner():
    sb = _rls_db()
    owner = _student(sb)
    memory_id = _memory(sb, owner)

    row = await cm.correct_memory(sb=sb, user=owner, memory_id=memory_id, importance="pinned")

    assert row["importance"] == "pinned"


# --- Cleanup failures never lose data ------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_failed_prune_leaves_every_memory_in_place_and_reports_it():
    sb = _rls_db()
    owner = _student(sb)
    _fresh_padding(sb, owner)
    _memory(sb, owner, days_old=800)
    before = len(sb.tables["chat_summaries"])

    async def broken_delete(table, filters):
        raise DataServiceError(503, "database unavailable")

    sb.delete_service = broken_delete

    result = await cm.prune_student_memories(sb=sb, user=owner, now=NOW)

    assert result.status == "error"
    assert len(sb.tables["chat_summaries"]) == before


@pytest.mark.asyncio
async def test_an_unexpected_error_during_prune_removes_nothing_and_does_not_raise():
    sb = _rls_db()
    owner = _student(sb)
    _fresh_padding(sb, owner)
    _memory(sb, owner, days_old=800)
    before = len(sb.tables["chat_summaries"])

    async def broken_select(*args, **kwargs):
        raise RuntimeError("unexpected")

    sb.select_service = broken_select

    result = await cm.prune_student_memories(sb=sb, user=owner, now=NOW)

    assert result.status == "error"
    assert len(sb.tables["chat_summaries"]) == before


# --- Cross-student isolation -------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_student_sees_only_their_own_memories_in_the_list():
    sb = _rls_db()
    alice, bob = _student(sb, "Alice"), _student(sb, "Bob")
    _memory(sb, alice, text="alice memory")
    _memory(sb, bob, text="bob memory")

    alices = await cm.list_memories(sb=sb, access_token=str(alice.id))

    assert [m["summary"] for m in alices] == ["alice memory"]


# --- Flag off: no query, no change ----------------------------------------------------------------

@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.setattr(settings, "chat_memory_context_enabled", False)


@pytest.mark.asyncio
async def test_flag_off_prune_returns_at_once_without_touching_the_database(flag_off):
    sb = NoTouchClient()
    user = SimpleNamespace(id=uuid4())

    result = await cm.prune_student_memories(sb=sb, user=user, now=NOW)

    assert result.status == "disabled" and result.removed == 0
    assert sb.touched == []


@pytest.mark.asyncio
async def test_flag_off_list_correct_and_delete_are_refused_without_touching_the_database(flag_off):
    user = SimpleNamespace(id=uuid4())
    sb = NoTouchClient()

    with pytest.raises(cm.MemoryDisabled):
        await cm.list_memories(sb=sb, access_token="t")
    with pytest.raises(cm.MemoryDisabled):
        await cm.correct_memory(sb=sb, user=user, memory_id=uuid4(), text="x")
    with pytest.raises(cm.MemoryDisabled):
        await cm.delete_memory(sb=sb, user=user, memory_id=uuid4())

    assert sb.touched == []


@pytest.mark.asyncio
async def test_flag_off_memory_endpoints_do_not_exist(flag_off):
    student = make_profile(str(uuid4()), role="student", campus_id=str(uuid4()))
    session = SimpleNamespace(user=student, access_token=str(student.id))
    memory_id = uuid4()
    sb = NoTouchClient()

    with pytest.raises(HTTPException) as listed:
        await chat_routes.my_memories(session=session, sb=sb)
    with pytest.raises(HTTPException) as corrected:
        await chat_routes.correct_my_memory(memory_id=memory_id, body=MemoryPatch(text="x"),
                                            session=session, sb=sb)
    with pytest.raises(HTTPException) as deleted:
        await chat_routes.delete_my_memory(memory_id=memory_id, session=session, sb=sb)

    assert listed.value.status_code == corrected.value.status_code == deleted.value.status_code == 404
    assert sb.touched == []


@pytest.mark.asyncio
async def test_flag_off_conversations_load_does_not_prune(flag_off, monkeypatch):
    student = make_profile(str(uuid4()), role="student", campus_id=str(uuid4()))
    session = SimpleNamespace(user=student, access_token=str(student.id))
    sb = FakeDataClient()
    sb.tables["messages"] = []
    calls = []

    async def no_tidy(**kwargs):
        return None

    async def record_prune(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat_routes, "tidy_student_chats_safely", no_tidy)
    monkeypatch.setattr(chat_routes, "get_ai_client", lambda: None)
    monkeypatch.setattr(chat_routes, "prune_student_memories", record_prune)

    page = await chat_routes.list_conversations(session=session, limit=20, offset=0, sb=sb)

    assert calls == []
    assert page.items == []


@pytest.mark.asyncio
async def test_flag_on_conversations_load_prunes_once(monkeypatch):
    student = make_profile(str(uuid4()), role="student", campus_id=str(uuid4()))
    session = SimpleNamespace(user=student, access_token=str(student.id))
    sb = FakeDataClient()
    sb.tables["messages"] = []
    calls = []

    async def no_tidy(**kwargs):
        return None

    async def record_prune(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(chat_routes, "tidy_student_chats_safely", no_tidy)
    monkeypatch.setattr(chat_routes, "get_ai_client", lambda: None)
    monkeypatch.setattr(chat_routes, "prune_student_memories", record_prune)

    await chat_routes.list_conversations(session=session, limit=20, offset=0, sb=sb)

    assert len(calls) == 1


# --- How memory may reach an answer ---------------------------------------------------------------------

def _evidence():
    return [Evidence(chunk_id=uuid4(), document_id=uuid4(), title="Official Policy", page_number=3,
                     content="Fees are paid by 1 September.", similarity=0.9)]


# --- Memory alone never answers; notes never support an uncited answer ----------------------------

# --- Flag off: the summariser and the memory reads ------------------------------------------------

BASE_SUMMARY_COLUMNS = {"id", "user_id", "conversation_id", "batch_key", "message_count",
                        "first_message_at", "last_message_at", "summary"}


def _old_chat(sb, owner, hours_old=90):
    conversation = str(uuid4())
    sb.tables["conversations"].append({"id": conversation, "user_id": str(owner.id), "title": "fixture",
                                       "created_at": _days_ago(10)})
    sb.tables["messages"].append({"id": str(uuid4()), "conversation_id": conversation, "role": "user",
                                  "content": "fixture question", "citations": [],
                                  "created_at": (NOW - timedelta(hours=hours_old)).isoformat()})
    return conversation


@pytest.mark.asyncio
async def test_flag_off_recent_summaries_do_not_query(flag_off):
    sb = NoTouchClient()

    assert await recent_summaries(sb, "fixture-token") == []
    assert sb.touched == []


@pytest.mark.asyncio
async def test_flag_off_the_summariser_still_runs_and_writes_only_the_original_columns(flag_off):
    sb = FakeDataClient()
    owner = _student(sb)
    _old_chat(sb, owner)
    written = []
    original_insert = sb.insert_service

    async def record(table, rows):
        if table == "chat_summaries":
            written.extend(rows)
        await original_insert(table, rows)

    sb.insert_service = record
    result = await tidy_student_chats(sb=sb, ai=FakeAI(reply="- Asked a fixture question."), user=owner, now=NOW)

    assert result["status"] == "summarized" and result["summary_created"] is True
    assert set(written[0]) == BASE_SUMMARY_COLUMNS  # independent of the unapplied migration's columns
    assert sb.tables["messages"] == []  # removed only after the summary was saved


@pytest.mark.asyncio
async def test_an_unexpected_summary_save_error_keeps_the_raw_messages():
    sb = FakeDataClient()
    owner = _student(sb)
    _old_chat(sb, owner)

    async def broken_insert(table, rows):
        if table == "chat_summaries":
            raise RuntimeError("unexpected")

    sb.insert_service = broken_insert
    result = await tidy_student_chats_safely(sb=sb, ai=FakeAI(reply="- Notes."), user=owner, now=NOW)

    assert result == {"status": "error"}
    assert len(sb.tables["messages"]) == 1
    assert sb.tables["chat_summaries"] == []


# --- Migration: least privilege ------------------------------------------------------------------

MIGRATION = Path(__file__).resolve().parents[1] / "app" / "db" / "migrations" / "20261119120000_chat_memory_ranking.sql"


def test_the_migration_grants_the_server_update_on_memory_columns_only():
    sql = MIGRATION.read_text()
    assert ("grant update (summary, importance, use_count, last_used_at, corrected_at) "
            "on public.chat_summaries to service_role;") in sql
    assert "grant update on" not in sql  # no whole-table update grant
    assert "to authenticated" not in sql and "to anon" not in sql  # students get no write grant
    assert "create policy" not in sql  # the owner-only read policy is defined by the earlier migration
