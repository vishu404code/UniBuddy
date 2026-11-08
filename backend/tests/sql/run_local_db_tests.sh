#!/bin/bash
# Rebuilds a LOCAL PostgreSQL test database from the migrations, then runs the SQL assertions.
# It never connects to the Supabase project. Requires PostgreSQL 17 with pgvector installed locally.
# Usage: PGBIN=/opt/homebrew/opt/postgresql@17/bin PGPORT=54329 tests/sql/run_local_db_tests.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
backend="$(cd "$here/../.." && pwd)"
PGBIN="${PGBIN:-/opt/homebrew/opt/postgresql@17/bin}"
PGPORT="${PGPORT:-54329}"
DB="${PGDATABASE_LOCAL:-unibuddy_test}"
export LC_ALL=en_US.UTF-8
psql_cmd() { "$PGBIN/psql" -h localhost -p "$PGPORT" -U postgres "$@"; }

psql_cmd -qc "drop database if exists $DB with (force);"
psql_cmd -qc "create database $DB;"
psql_cmd -d "$DB" -v ON_ERROR_STOP=1 -q <<'SQL'
do $$ begin
  if not exists (select from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end $$;
grant anon, authenticated, service_role to postgres;
create schema auth;
create table auth.users (id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$
  select nullif(nullif(current_setting('request.jwt.claims', true), '')::json->>'sub', '')::uuid
$$;
grant usage on schema auth to anon, authenticated, service_role;
grant execute on function auth.uid() to anon, authenticated, service_role;
SQL
for f in "$backend"/supabase/migrations/*.sql; do
  psql_cmd -d "$DB" -v ON_ERROR_STOP=1 -q --single-transaction -f "$f"
done
psql_cmd -d "$DB" -v ON_ERROR_STOP=1 -q -f "$here/document_lifecycle_test.sql" 2>&1 | grep -E "NOTICE|ERROR" | sed 's/^.*NOTICE:  //'
echo "local SQL assertions finished"
