-- UniBuddy access helpers for the replacement database (Stage 1).
--
-- Helpers that read the signed-in user from app.user_id. The backend sets
-- app.user_id for each transaction (see app/db/postgres.py set_session_user).
-- With no user set, every helper returns NULL, so policies that compare against
-- them match nothing. Profiles are read with SECURITY DEFINER so policies on other
-- tables don't recurse into profile policies.

create schema if not exists unibuddy_auth;

create or replace function unibuddy_auth.user_id()
returns uuid
language sql
stable
as $$
  select nullif(current_setting('app.user_id', true), '')::uuid
$$;

create or replace function unibuddy_auth.app_role()
returns text
language sql
stable
security definer
set search_path = public
as $$
  select p.role from public.profiles p where p.id = unibuddy_auth.user_id()
$$;

create or replace function unibuddy_auth.campus_id()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select p.campus_id from public.profiles p where p.id = unibuddy_auth.user_id()
$$;

create or replace function unibuddy_auth.department_id()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select p.department_id from public.profiles p where p.id = unibuddy_auth.user_id()
$$;

revoke all on function unibuddy_auth.user_id() from public;
revoke all on function unibuddy_auth.app_role() from public;
revoke all on function unibuddy_auth.campus_id() from public;
revoke all on function unibuddy_auth.department_id() from public;
