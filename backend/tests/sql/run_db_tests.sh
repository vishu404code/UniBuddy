#!/bin/bash
# Rebuilds a LOCAL database from the bootstrap and migrations, then runs the SQL assertions.
# It runs only against a local PostgreSQL 17 server with pgvector. It never connects to a cloud database.
# Usage: PGPORT=54329 PGUSER_LOCAL=<your-local-user> tests/sql/run_db_tests.sh
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
for t in "$here"/*_test.sql; do
  echo "== $(basename "$t")"
  db_cmd -f "$t" 2>&1 | grep -E "NOTICE|ERROR" | grep -v "already been granted" | sed 's/^.*NOTICE:  //' || true
done
echo "local SQL assertions finished"
