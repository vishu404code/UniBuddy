-- Bootstrap for the replacement database. Run once, before the migrations in app/db/migrations.
--
-- Roles: the migrations use the same three role names as before. They are ordinary
-- Postgres roles here. The backend's own login role must be a non-superuser that is
-- granted these roles. Only service_role bypasses row policies, and the backend uses it
-- only for server-side work such as the document worker.
--
-- The user comes from the app.user_id setting, set per transaction by the backend.

do $$
begin
  if not exists (select from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end $$;

create schema if not exists unibuddy_auth;

create or replace function unibuddy_auth.user_id()
returns uuid
language sql
stable
as $$
  select nullif(current_setting('app.user_id', true), '')::uuid
$$;

revoke all on function unibuddy_auth.user_id() from public;
grant usage on schema unibuddy_auth to anon, authenticated, service_role;
grant execute on function unibuddy_auth.user_id() to anon, authenticated, service_role;
