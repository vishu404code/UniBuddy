"""READ-ONLY export of the Supabase project into a snapshot folder. Not run during development.

It issues only GET requests (PostgREST, Auth admin list, Storage download). It never writes to,
pauses, or deletes anything in Supabase. Run it only after the migration plan is approved.

Usage (from backend/):
  .venv/bin/python tools/migration/export_supabase.py --out /secure/folder/outside/the/repo

Secrets are read from backend/.env and are never printed. The output folder must be outside the
Git repository, because it contains real personal data.
"""

import argparse
import json
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import certifi

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.migration.snapshot import IMPORT_ORDER, SnapshotError, write_snapshot  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
PAGE = 1000


def _env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (Path(__file__).resolve().parents[2] / ".env").read_text().splitlines():
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _get(url: str, key: str, ctx) -> tuple[bytes, dict]:
    request = urllib.request.Request(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(request, context=ctx, timeout=60) as response:
        return response.read(), dict(response.headers)


def _all_rows(base: str, table: str, key: str, ctx) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        query = urllib.parse.urlencode({"select": "*", "order": "id.asc", "limit": PAGE, "offset": offset})
        body, _ = _get(f"{base}/rest/v1/{table}?{query}", key, ctx)
        page = json.loads(body)
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        offset += PAGE


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if REPO in out.parents or out == REPO:
        raise SystemExit("refusing: the output folder must be outside the Git repository")

    env = _env()
    base = env["SUPABASE_URL"].rstrip("/")
    key = env["SUPABASE_SECRET_KEY"]
    ctx = ssl.create_default_context(cafile=certifi.where())

    tables = {name: _all_rows(base, name, key, ctx) for name in IMPORT_ORDER if name != "account_identities"}

    # Accounts come from Supabase Auth. Password hashes are never exported.
    users_body, _ = _get(f"{base}/auth/v1/admin/users?per_page=1000", key, ctx)
    users = json.loads(users_body)
    users = users.get("users", users)
    tables["account_identities"] = [
        {"id": u["id"], "email": (u.get("email") or "").lower(), "google_subject": None,
         "created_at": u.get("created_at")}
        for u in users
    ]

    files = {}
    for document in tables["documents"]:
        body, _ = _get(f"{base}/storage/v1/object/documents/{document['storage_path']}", key, ctx)
        files[document["storage_path"]] = body

    manifest = write_snapshot(out, tables, files)
    try:
        from tools.migration.snapshot import verify_snapshot

        verify_snapshot(out)
    except SnapshotError as exc:
        raise SystemExit(f"export failed verification: {exc}")
    print({name: meta["rows"] for name, meta in manifest["tables"].items()}, "files:", len(files))


if __name__ == "__main__":
    main()
