"""Generates Supabase-free copies of the migrations and SQL tests.

Run from backend/:  python tools/port_supabase_migrations.py

Source files in supabase/ are never modified. The generated files are checked in, so
review them in Git. The transform is small and deterministic:

- auth.uid()                      -> unibuddy_auth.user_id()
- references auth.users(id)       -> references public.account_identities(id)
- auth.users                      -> public.account_identities
- set_config('request.jwt.claims', '{"sub":"<id>",...}') -> set_config('app.user_id', '<id>')

The script fails if any reference to the Supabase auth schema is left behind.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_MIGRATIONS = ROOT / "supabase" / "migrations"
OUT_MIGRATIONS = ROOT / "app" / "db" / "migrations"
SRC_TESTS = ROOT / "tests" / "sql"
OUT_TESTS = ROOT / "tests" / "sql_portable"

LEFTOVER = re.compile(r"(?<![A-Za-z_@.])auth\.(uid|users|jwt|role)\b")
JWT_SUB = re.compile(r"select set_config\('request\.jwt\.claims', '\{\"sub\":\"([0-9a-f-]+)\"[^']*\}', false\)")


def _check(text: str, name: str) -> str:
    if LEFTOVER.search(text):
        raise SystemExit(f"{name}: a Supabase auth reference was not transformed")
    return text


def port_migration(text: str) -> str:
    text = text.replace("references auth.users(id)", "references public.account_identities(id)")
    text = re.sub(r"(?<![A-Za-z_])auth\.uid\(\)", "unibuddy_auth.user_id()", text)
    text = re.sub(r"(?<![A-Za-z_])auth\.users\b", "public.account_identities", text)
    return text


def port_test(text: str) -> str:
    text = JWT_SUB.sub(r"select set_config('app.user_id', '\1', false)", text)
    text = re.sub(r"(?<![A-Za-z_])auth\.users\b", "public.account_identities", text)
    return text


def _header(source: Path) -> str:
    return f"-- GENERATED from {source.relative_to(ROOT)} by tools/port_supabase_migrations.py. Do not edit by hand.\n"


def main() -> None:
    OUT_MIGRATIONS.mkdir(parents=True, exist_ok=True)
    OUT_TESTS.mkdir(parents=True, exist_ok=True)
    for source in sorted(SRC_MIGRATIONS.glob("*.sql")):
        body = port_migration(source.read_text())
        _check(body, source.name)
        (OUT_MIGRATIONS / source.name).write_text(_header(source) + body)
    for source in sorted(SRC_TESTS.glob("*_test.sql")):
        body = port_test(source.read_text())
        _check(body, source.name)
        (OUT_TESTS / source.name).write_text(_header(source) + body)
    print(f"ported {len(list(OUT_MIGRATIONS.glob('*.sql')))} migrations and {len(list(OUT_TESTS.glob('*.sql')))} tests")


if __name__ == "__main__":
    main()
