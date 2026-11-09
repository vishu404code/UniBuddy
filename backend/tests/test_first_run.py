"""First-run setup, tested on a fresh local database. Needs TEST_DATABASE_URL (an owner connection to
any local database). The test creates and drops `unibuddy_first_run_test`. Skipped without it."""

import os
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import first_run  # noqa: E402

ADMIN_DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="TEST_DATABASE_URL is not set")
NAME = "unibuddy_first_run_test"


def _dsn():
    return ADMIN_DSN.rsplit("/", 1)[0] + "/" + NAME


@pytest.fixture
def empty_db():
    base = ADMIN_DSN.rsplit("/", 1)[0]
    with psycopg.connect(f"{base}/postgres", autocommit=True) as admin:
        admin.execute(f"drop database if exists {NAME} with (force)")
        admin.execute(f"create database {NAME}")
    yield _dsn()
    with psycopg.connect(f"{base}/postgres", autocommit=True) as admin:
        admin.execute(f"drop database if exists {NAME} with (force)")


def _connect(dsn):
    return psycopg.connect(dsn, row_factory=dict_row)


def test_schema_step_creates_the_tables_on_an_empty_database(empty_db):
    with _connect(empty_db) as conn:
        applied = first_run.apply_schema(conn)
        conn.commit()
    assert "00_roles_and_access.sql" in applied
    with _connect(empty_db) as conn:
        tables = {r["table_name"] for r in conn.execute(
            "select table_name from information_schema.tables where table_schema = 'public'").fetchall()}
    assert {"profiles", "documents", "document_chunks", "account_identities", "campuses"} <= tables


def test_schema_step_refuses_a_database_that_already_has_tables(empty_db):
    with _connect(empty_db) as conn:
        first_run.apply_schema(conn)
        conn.commit()
    with _connect(empty_db) as conn:
        with pytest.raises(first_run.BootstrapRefused):
            first_run.apply_schema(conn)


def test_authority_step_creates_the_campus_and_one_authority_profile(empty_db):
    with _connect(empty_db) as conn:
        first_run.apply_schema(conn)
        conn.commit()
    email = f"first.authority.{uuid4().hex[:8]}@example.test"
    with _connect(empty_db) as conn:
        result = first_run.bootstrap_authority(conn, campus_name="Test Campus", campus_code="test-campus",
                                               email=email.upper(), full_name="First  Authority")
        conn.commit()
    with _connect(empty_db) as conn:
        profile = conn.execute("select id, email, role, campus_id, full_name from public.profiles").fetchone()
    assert profile["role"] == "authority"
    assert profile["email"] == email
    assert profile["full_name"] == "First Authority"
    assert str(profile["id"]) == result["account_id"]
    assert str(profile["campus_id"]) == result["campus_id"]


def test_authority_step_runs_only_once(empty_db):
    with _connect(empty_db) as conn:
        first_run.apply_schema(conn)
        first_run.bootstrap_authority(conn, campus_name="Test Campus", campus_code="c1",
                                      email="one@example.test", full_name="One Person")
        conn.commit()
    with _connect(empty_db) as conn:
        with pytest.raises(first_run.BootstrapRefused, match="already exists"):
            first_run.bootstrap_authority(conn, campus_name="Test Campus", campus_code="c1",
                                          email="two@example.test", full_name="Two Person")


def test_authority_step_refuses_a_campus_code_with_a_different_name(empty_db):
    with _connect(empty_db) as conn:
        first_run.apply_schema(conn)
        conn.execute("insert into public.campuses (name, code) values ('Other', 'c2')")
        conn.commit()
    with _connect(empty_db) as conn:
        with pytest.raises(first_run.BootstrapRefused, match="different name"):
            first_run.bootstrap_authority(conn, campus_name="Test Campus", campus_code="c2",
                                          email="one@example.test", full_name="One Person")


def test_authority_step_rejects_bad_input_and_writes_nothing(empty_db):
    with _connect(empty_db) as conn:
        first_run.apply_schema(conn)
        conn.commit()
        with pytest.raises(first_run.BootstrapRefused):
            first_run.bootstrap_authority(conn, campus_name="C", campus_code="c3",
                                          email="not-an-email", full_name="One Person")
        conn.rollback()
    with _connect(empty_db) as conn:
        assert conn.execute("select count(*) as n from public.campuses").fetchone()["n"] == 0


def test_owner_url_for_a_supabase_host_is_refused(monkeypatch):
    monkeypatch.setenv("OWNER_DATABASE_URL", "postgresql://u:p@db.xbpbnzcfnrcljjfuwhhy.supabase.co:5432/postgres")
    with pytest.raises(SystemExit):
        first_run._owner_dsn()


def test_owner_url_is_required(monkeypatch):
    monkeypatch.delenv("OWNER_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        first_run._owner_dsn()
