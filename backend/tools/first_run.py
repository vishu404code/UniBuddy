"""First-run setup for an empty UniBuddy database, run by the owner. Not part of the web app.

Two steps, each run once:

  1. schema:    applies app/db/bootstrap and app/db/migrations to an empty database.
  2. authority: creates the campus (if missing) and the first Authority account, and refuses
                if any Authority already exists. Google sign-in then links the person to that
                account by its verified email. No password, no public signup, no role field.

The owner connection string is read from OWNER_DATABASE_URL. It is never the backend's own
role and is never printed. Run from backend/:

  OWNER_DATABASE_URL=... .venv/bin/python tools/first_run.py schema --confirm
  OWNER_DATABASE_URL=... .venv/bin/python tools/first_run.py authority \
      --campus-name "Rishihood University, Sonipat" --campus-code sonipat \
      --email <your-university-or-google-email> --full-name "<your name>" --confirm
"""

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "app" / "db" / "bootstrap" / "00_roles_and_access.sql"
MIGRATIONS = ROOT / "app" / "db" / "migrations"
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SUPABASE_HOST = re.compile(r"(^|[./@])supabase\.(co|com|in)\b", re.IGNORECASE)


class BootstrapRefused(Exception):
    """A safety rule stopped the step. Nothing was written."""


def _refuse_supabase(dsn: str) -> None:
    if SUPABASE_HOST.search(dsn or ""):
        raise BootstrapRefused("refusing: this is a Supabase host")


def apply_schema(conn) -> list[str]:
    """Creates the schema in an empty database. Refuses if the database already has tables."""
    existing = conn.execute(
        "select count(*) as n from information_schema.tables where table_schema = 'public'"
    ).fetchone()["n"]
    if existing:
        raise BootstrapRefused("the database already has tables; the schema step only runs on an empty database")
    applied = []
    conn.execute(BOOTSTRAP.read_text())
    applied.append(BOOTSTRAP.name)
    for path in sorted(MIGRATIONS.glob("*.sql")):
        conn.execute(path.read_text())
        applied.append(path.name)
    return applied


def bootstrap_authority(conn, *, campus_name: str, campus_code: str, email: str, full_name: str) -> dict:
    """Creates the first Authority. Runs in one transaction; the caller commits."""
    email = email.strip().lower()
    campus_name = campus_name.strip()
    campus_code = campus_code.strip().lower()
    full_name = " ".join(full_name.split())
    if not EMAIL.match(email):
        raise BootstrapRefused("enter a valid email address")
    if not campus_name or not campus_code or len(full_name) < 2:
        raise BootstrapRefused("campus name, campus code and full name are required")

    if conn.execute("select 1 from public.profiles where role = 'authority' limit 1").fetchone():
        raise BootstrapRefused("an Authority already exists; this one-time step has already run")
    if conn.execute("select 1 from public.profiles where email = %s", (email,)).fetchone():
        raise BootstrapRefused("a profile already exists for this email")

    campus = conn.execute("select id, name from public.campuses where code = %s", (campus_code,)).fetchone()
    if campus is None:
        campus = conn.execute(
            "insert into public.campuses (name, code) values (%s, %s) returning id, name",
            (campus_name, campus_code),
        ).fetchone()
    elif campus["name"] != campus_name:
        raise BootstrapRefused("a campus with this code already exists under a different name")

    accounts = conn.execute(
        "select id from public.account_identities where email = %s", (email,)
    ).fetchall()
    if len(accounts) > 1:
        raise BootstrapRefused("more than one account row uses this email; resolve it before bootstrapping")
    if accounts:
        account_id = accounts[0]["id"]
    else:
        account_id = conn.execute(
            "insert into public.account_identities (email) values (%s) returning id", (email,)
        ).fetchone()["id"]

    conn.execute(
        "insert into public.profiles (id, email, full_name, role, campus_id, department_id, cross_campus_record_access) "
        "values (%s, %s, %s, 'authority', %s, null, false)",
        (account_id, email, full_name, campus["id"]),
    )
    return {"account_id": str(account_id), "campus_id": str(campus["id"]), "campus_name": campus["name"]}


def _owner_dsn() -> str:
    dsn = os.environ.get("OWNER_DATABASE_URL", "")
    if not dsn:
        raise SystemExit("OWNER_DATABASE_URL is not set")
    try:
        _refuse_supabase(dsn)
    except BootstrapRefused as exc:
        raise SystemExit(f"Stopped: {exc}. Nothing was written.")
    return dsn


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="step", required=True)
    sub.add_parser("schema").add_argument("--confirm", action="store_true", required=True)
    auth = sub.add_parser("authority")
    auth.add_argument("--campus-name", required=True)
    auth.add_argument("--campus-code", required=True)
    auth.add_argument("--email", required=True)
    auth.add_argument("--full-name", required=True)
    auth.add_argument("--confirm", action="store_true", required=True)
    args = parser.parse_args(argv)

    try:
        with psycopg.connect(_owner_dsn(), row_factory=dict_row) as conn:
            if args.step == "schema":
                applied = apply_schema(conn)
                conn.commit()
                print(f"Applied {len(applied)} files: {', '.join(applied)}")
            else:
                result = bootstrap_authority(
                    conn, campus_name=args.campus_name, campus_code=args.campus_code,
                    email=args.email, full_name=args.full_name,
                )
                conn.commit()
                print(f"Authority created for campus {result['campus_name']}. Sign in with Google using that email.")
    except BootstrapRefused as exc:
        raise SystemExit(f"Stopped: {exc}. Nothing was written.")


if __name__ == "__main__":
    main(sys.argv[1:])
