"""Snapshot format, verification and import for moving UniBuddy data off Supabase.

A snapshot is a folder:
  manifest.json                 table row counts and SHA-256 of each table file; file hashes
  tables/<table>.jsonl          one JSON object per row, in import order
  files/<campus>/<doc>.pdf      stored PDFs, byte for byte

The import runs as the database owner, never as the backend's role. It refuses to write into a
database that already has data, and it refuses Supabase hosts, so it cannot be pointed at the
live project by mistake. Verification compares counts, hashes, foreign keys and embedding sizes
before anything is reported as migrated.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

FORMAT_VERSION = 1
EMBEDDING_DIMENSIONS = 1536

# Parents before children, so foreign keys are satisfied as rows are inserted.
IMPORT_ORDER = [
    "account_identities",
    "campuses",
    "departments",
    "profiles",
    "documents",
    "document_chunks",
    "conversations",
    "messages",
    "announcements",
    "tickets",
    "ticket_events",
    "notifications",
    "registration_requests",
    "provisioning_audit",
]
TICKET_SEQUENCE = "public.ticket_number_seq"
SUPABASE_HOST = re.compile(r"(^|[./@])supabase\.(co|com|in)\b", re.IGNORECASE)


class SnapshotError(Exception):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def table_bytes(rows: list[dict[str, Any]]) -> bytes:
    lines = [json.dumps(row, sort_keys=True, default=str, separators=(",", ":")) for row in rows]
    return ("\n".join(lines) + ("\n" if lines else "")).encode()


def write_snapshot(folder: Path, tables: dict[str, list[dict[str, Any]]], files: dict[str, bytes]) -> dict:
    """Writes a snapshot. Used by the export and by the tests. Returns the manifest."""
    unknown = set(tables) - set(IMPORT_ORDER)
    if unknown:
        raise SnapshotError(f"unknown tables: {sorted(unknown)}")
    (folder / "tables").mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"format": FORMAT_VERSION, "tables": {}, "files": {}}
    for name in IMPORT_ORDER:
        rows = tables.get(name, [])
        data = table_bytes(rows)
        (folder / "tables" / f"{name}.jsonl").write_bytes(data)
        manifest["tables"][name] = {"rows": len(rows), "sha256": sha256_bytes(data)}
    for key, data in files.items():
        _check_file_key(key)
        target = folder / "files" / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest["files"][key] = {"sha256": sha256_bytes(data), "size": len(data)}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def _check_file_key(key: str) -> None:
    if not re.fullmatch(r"[0-9a-f-]{36}/[0-9a-f-]{36}\.pdf", key):
        raise SnapshotError("file key does not match the upload layout")


def verify_snapshot(folder: Path) -> dict:
    """Checks the manifest against the files on disk. Raises SnapshotError on any mismatch."""
    manifest_path = folder / "manifest.json"
    if not manifest_path.exists():
        raise SnapshotError("manifest.json is missing")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("format") != FORMAT_VERSION:
        raise SnapshotError("unsupported snapshot format")
    for name, meta in manifest["tables"].items():
        path = folder / "tables" / f"{name}.jsonl"
        data = path.read_bytes() if path.exists() else b""
        if sha256_bytes(data) != meta["sha256"]:
            raise SnapshotError(f"table file changed or missing: {name}")
        if len([line for line in data.decode().splitlines() if line]) != meta["rows"]:
            raise SnapshotError(f"row count does not match the manifest: {name}")
    for key, meta in manifest["files"].items():
        path = folder / "files" / key
        if not path.exists():
            raise SnapshotError("a stored file is missing")
        data = path.read_bytes()
        if sha256_bytes(data) != meta["sha256"] or len(data) != meta["size"]:
            raise SnapshotError("a stored file does not match its hash")
    return manifest


def load_rows(folder: Path, table: str) -> list[dict[str, Any]]:
    path = folder / "tables" / f"{table}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def refuse_supabase_target(dsn: str) -> None:
    if SUPABASE_HOST.search(dsn or ""):
        raise SnapshotError("refusing to import into a Supabase host")


def import_snapshot(conn, folder: Path) -> dict[str, int]:
    """Inserts every table in order. Refuses a target that already has data.

    `conn` must be an owner connection. The caller commits or rolls back, so the whole import
    is one transaction: either every table lands or none does.
    """
    verify_snapshot(folder)
    for table in ("profiles", "documents", "campuses"):
        existing = conn.execute(f"select count(*) as n from public.{table}").fetchone()["n"]
        if existing:
            raise SnapshotError(f"target already has rows in {table}; import into an empty database")

    from psycopg.types.json import Json

    counts: dict[str, int] = {}
    for table in IMPORT_ORDER:
        rows = load_rows(folder, table)
        counts[table] = len(rows)
        for row in rows:
            columns = list(row.keys())
            placeholders = ", ".join(["%s"] * len(columns))
            column_sql = ", ".join(f'"{c}"' for c in columns)
            values = [Json(v) if isinstance(v, (dict, list)) else v for v in row.values()]
            conn.execute(f'insert into public."{table}" ({column_sql}) values ({placeholders})', values)

    if counts.get("tickets"):
        conn.execute(
            "select setval(%s, (select coalesce(max(substring(ticket_number from 4)::int), 0) from public.tickets))",
            (TICKET_SEQUENCE,),
        )
    return counts


def verify_database(conn, folder: Path) -> list[str]:
    """Read-only checks after an import. Returns a list of problems; an empty list means verified."""
    manifest = verify_snapshot(folder)
    problems: list[str] = []
    for table, meta in manifest["tables"].items():
        actual = conn.execute(f'select count(*) as n from public."{table}"').fetchone()["n"]
        if actual != meta["rows"]:
            problems.append(f"{table}: expected {meta['rows']} rows, found {actual}")
    bad_vectors = conn.execute(
        "select count(*) as n from public.document_chunks where vector_dims(embedding) <> %s",
        (EMBEDDING_DIMENSIONS,),
    ).fetchone()["n"]
    if bad_vectors:
        problems.append(f"{bad_vectors} chunks do not have {EMBEDDING_DIMENSIONS}-dimension embeddings")
    orphan_docs = conn.execute(
        "select count(*) as n from public.documents d left join public.profiles p on p.id = d.uploaded_by "
        "where p.id is null"
    ).fetchone()["n"]
    if orphan_docs:
        problems.append(f"{orphan_docs} documents point at an uploader who is not in profiles")
    return problems
