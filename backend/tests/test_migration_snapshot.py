"""Snapshot tooling, tested only with synthetic data.

No Supabase or cloud database is contacted. The import test needs TEST_DATABASE_URL pointing at a
local PostgreSQL server as an owner. It creates and drops its own database, unibuddy_import_test.
"""

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.migration import export_supabase  # noqa: E402
from tools.migration.snapshot import (  # noqa: E402
    SnapshotError,
    import_snapshot,
    refuse_supabase_target,
    verify_database,
    verify_snapshot,
    write_snapshot,
)

ADMIN_DSN = os.environ.get("TEST_DATABASE_URL")
AUTHORITY = uuid4()
CAMPUS = uuid4()
DOC = uuid4()
KEY = f"{CAMPUS}/{DOC}.pdf"
PDF = b"%PDF-1.4 synthetic test document"
VECTOR = "[" + ",".join(["0.001"] * 1536) + "]"


def _connect(dsn, **kwargs):
    return psycopg.connect(dsn, row_factory=dict_row, **kwargs)


def _tables():
    return {
        "account_identities": [{"id": str(AUTHORITY), "email": "authority@example.test",
                                "google_subject": None, "created_at": "2026-11-08T00:00:00+00:00"}],
        "campuses": [{"id": str(CAMPUS), "name": f"Snapshot {CAMPUS.hex[:8]}", "code": f"snap-{CAMPUS.hex[:10]}"}],
        "profiles": [{"id": str(AUTHORITY), "email": "authority@example.test", "role": "authority",
                      "campus_id": str(CAMPUS), "department_id": None, "cross_campus_record_access": False,
                      "metadata": {}}],
        "documents": [{"id": str(DOC), "title": "Synthetic policy", "original_filename": "policy.pdf",
                       "mime_type": "application/pdf", "file_size_bytes": len(PDF), "storage_path": KEY,
                       "uploaded_by": str(AUTHORITY), "campus_id": str(CAMPUS), "department_id": None,
                       "scope": "university_wide", "visibility": "public_students",
                       "processing_status": "ready", "publication_status": "published", "page_count": 1}],
        "document_chunks": [{"id": str(uuid4()), "document_id": str(DOC), "chunk_index": 0, "page_number": 1,
                             "content": "Synthetic content.", "embedding": VECTOR}],
    }


# --- format and hashes (no database) ---------------------------------------------------

def test_snapshot_round_trip_verifies(tmp_path):
    write_snapshot(tmp_path, _tables(), {KEY: PDF})

    manifest = verify_snapshot(tmp_path)

    assert manifest["tables"]["documents"]["rows"] == 1
    assert manifest["files"][KEY]["size"] == len(PDF)


def test_changed_table_file_is_detected(tmp_path):
    write_snapshot(tmp_path, _tables(), {KEY: PDF})
    path = tmp_path / "tables" / "documents.jsonl"
    path.write_text(path.read_text().replace("Synthetic policy", "Edited policy"))

    with pytest.raises(SnapshotError, match="changed or missing: documents"):
        verify_snapshot(tmp_path)


def test_changed_stored_file_is_detected(tmp_path):
    write_snapshot(tmp_path, _tables(), {KEY: PDF})
    (tmp_path / "files" / KEY).write_bytes(b"%PDF-1.4 altered")

    with pytest.raises(SnapshotError, match="stored file does not match"):
        verify_snapshot(tmp_path)


def test_missing_stored_file_is_detected(tmp_path):
    write_snapshot(tmp_path, _tables(), {KEY: PDF})
    (tmp_path / "files" / KEY).unlink()

    with pytest.raises(SnapshotError, match="missing"):
        verify_snapshot(tmp_path)


def test_file_key_outside_the_upload_layout_is_refused(tmp_path):
    with pytest.raises(SnapshotError):
        write_snapshot(tmp_path, _tables(), {"../escape.pdf": PDF})


def test_unknown_table_is_refused(tmp_path):
    with pytest.raises(SnapshotError):
        write_snapshot(tmp_path, {"auth_users_raw": []}, {})


def test_supabase_hosts_are_refused_as_import_targets():
    with pytest.raises(SnapshotError):
        refuse_supabase_target("postgresql://u:p@db.xbpbnzcfnrcljjfuwhhy.supabase.co:5432/postgres")
    refuse_supabase_target("postgresql://u:p@ep-example.us-east-2.aws.neon.tech/unibuddy?sslmode=require")


def test_export_refuses_an_output_folder_inside_the_repository(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["export", "--out", str(ROOT / "exported")])

    with pytest.raises(SystemExit) as info:
        export_supabase.main()

    assert "outside the Git repository" in str(info.value)


# --- import and database checks (local owner database only) ------------------------------

@pytest.fixture
def import_db(tmp_path):
    if not ADMIN_DSN:
        pytest.skip("TEST_DATABASE_URL is not set")
    base = ADMIN_DSN.rsplit("/", 1)[0]
    name = "unibuddy_import_test"
    with _connect(f"{base}/postgres", autocommit=True) as admin:
        admin.execute(f"drop database if exists {name} with (force)")
        admin.execute(f"create database {name}")
    dsn = f"{base}/{name}"
    with _connect(dsn, autocommit=True) as conn:
        conn.execute((ROOT / "app/db/bootstrap/00_roles_and_access.sql").read_text())
        for migration in sorted((ROOT / "app/db/migrations").glob("*.sql")):
            conn.execute(migration.read_text())
    try:
        yield dsn
    finally:
        with _connect(f"{base}/postgres", autocommit=True) as admin:
            admin.execute(f"drop database if exists {name} with (force)")


def test_import_then_verify_preserves_ids_files_hashes_and_embeddings(import_db, tmp_path):
    write_snapshot(tmp_path, _tables(), {KEY: PDF})

    with _connect(import_db) as conn:
        counts = import_snapshot(conn, tmp_path)
        conn.commit()

    assert counts["documents"] == 1
    with _connect(import_db) as conn:
        assert verify_database(conn, tmp_path) == []
        stored = conn.execute("select id, uploaded_by from public.documents").fetchall()
        assert [(row["id"], row["uploaded_by"]) for row in stored] == [(DOC, AUTHORITY)]
        profile = conn.execute("select role, campus_id from public.profiles where id = %s", (AUTHORITY,)).fetchone()
        assert (profile["role"], profile["campus_id"]) == ("authority", CAMPUS)


def test_import_refuses_a_database_that_already_has_data(import_db, tmp_path):
    write_snapshot(tmp_path, _tables(), {KEY: PDF})
    with _connect(import_db) as conn:
        import_snapshot(conn, tmp_path)
        conn.commit()

    with _connect(import_db) as conn:
        with pytest.raises(SnapshotError, match="already has rows"):
            import_snapshot(conn, tmp_path)


def test_failed_import_leaves_nothing_behind(import_db, tmp_path):
    tables = _tables()
    tables["document_chunks"][0]["embedding"] = "[0.1,0.2]"  # wrong size: the insert must fail
    write_snapshot(tmp_path, tables, {KEY: PDF})

    with _connect(import_db) as conn:
        with pytest.raises(psycopg.Error):
            import_snapshot(conn, tmp_path)
        conn.rollback()

    with _connect(import_db) as conn:
        assert conn.execute("select count(*) as n from public.campuses").fetchone()["n"] == 0
