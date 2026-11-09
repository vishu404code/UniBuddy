#!/bin/bash
# Rebuilds a LOCAL database from the Supabase-free bootstrap and migrations, then runs the ported SQL tests.
# It never connects to Supabase or any cloud database.
# Usage: PGPORT=54329 tests/sql/run_portable_db_tests.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
backend="$(cd "$here/../.." && pwd)"
PGBIN="${PGBIN:-/opt/homebrew/opt/postgresql@17/bin}"
PGPORT="${PGPORT:-54329}"
PGUSER_LOCAL="${PGUSER_LOCAL:-$(whoami)}"
DB="${PGDATABASE_LOCAL:-unibuddy_portable}"
export LC_ALL=en_US.UTF-8
psql_cmd() { "$PGBIN/psql" -h localhost -p "$PGPORT" -U "$PGUSER_LOCAL" -d postgres -v ON_ERROR_STOP=1 -q "$@"; }
db_cmd() { "$PGBIN/psql" -h localhost -p "$PGPORT" -U "$PGUSER_LOCAL" -d "$DB" -v ON_ERROR_STOP=1 -q "$@"; }

psql_cmd -c "drop database if exists $DB with (force);"
psql_cmd -c "create database $DB;"
db_cmd -f "$backend/app/db/bootstrap/00_roles_and_access.sql"
db_cmd -c "grant anon, authenticated, service_role to $PGUSER_LOCAL;"
for f in "$backend"/app/db/migrations/*.sql; do
  db_cmd --single-transaction -f "$f"
done
for t in "$here"/../sql_portable/*_test.sql; do
  echo "== $(basename "$t")"
  db_cmd -f "$t" 2>&1 | grep -E "NOTICE|ERROR" | grep -v "already been granted" | sed 's/^.*NOTICE:  //' || true
done
echo "ported local SQL assertions finished"
