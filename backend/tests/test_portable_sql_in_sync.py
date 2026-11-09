"""The ported SQL files must match what the generator produces from supabase/.

No database is needed. If someone edits a generated file by hand, or changes the
Supabase migrations without regenerating, this test fails.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("port", ROOT / "tools" / "port_supabase_migrations.py")
port = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(port)


def _expected(source: Path, transform):
    return port._header(source) + transform(source.read_text())


def test_generated_migrations_match_the_generator_output():
    for source in sorted(port.SRC_MIGRATIONS.glob("*.sql")):
        generated = port.OUT_MIGRATIONS / source.name
        assert generated.read_text() == _expected(source, port.port_migration), source.name


def test_generated_tests_match_the_generator_output():
    for source in sorted(port.SRC_TESTS.glob("*_test.sql")):
        generated = port.OUT_TESTS / source.name
        assert generated.read_text() == _expected(source, port.port_test), source.name


def test_no_supabase_auth_reference_remains_in_the_generated_files():
    # account_identities.sql is written by hand and only mentions Supabase in a comment.
    generated = [
        path
        for path in list(port.OUT_MIGRATIONS.glob("*.sql")) + list(port.OUT_TESTS.glob("*.sql"))
        if path.read_text().startswith("-- GENERATED")
    ]
    assert generated
    for path in generated:
        assert not port.LEFTOVER.search(path.read_text()), path.name


def test_bootstrap_defines_no_supabase_schema():
    text = (ROOT / "app" / "db" / "bootstrap" / "00_roles_and_access.sql").read_text()

    assert "create schema if not exists auth" not in text
    assert "auth.uid()" not in text
