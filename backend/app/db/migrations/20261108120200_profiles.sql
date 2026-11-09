-- Profiles (roles, campus, department) and the RLS helper functions that
-- policies in later migrations depend on.
--
-- Profiles are not created by a signup trigger: role and campus are assigned
-- by the backend using the secret key. Self-selected roles or campuses
-- at signup would let anyone grant themselves staff access.

create table public.profiles (
  id uuid primary key references public.account_identities(id) on delete cascade,
  email text not null unique,
  full_name text,
  role text not null default 'student'
    check (role in ('student', 'faculty', 'authority', 'management')),
  campus_id uuid references public.campuses(id),
  department_id uuid,
  -- Explicit grant for individual cross-campus record access. Only management may hold it,
  -- and it is set by the backend, never at signup.
  cross_campus_record_access boolean not null default false,
  -- Flexible extra fields the frontend's onboarding already collects
  -- (e.g. course, age) without forcing a schema change for each one.
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint profiles_department_in_campus
    foreign key (department_id, campus_id)
    references public.departments(id, campus_id),
  constraint profiles_department_requires_campus
    check (department_id is null or campus_id is not null),
  constraint profiles_cross_campus_only_management
    check (cross_campus_record_access = false or role = 'management')
);

create index profiles_campus_id_idx on public.profiles(campus_id);
create index profiles_role_idx on public.profiles(role);

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute function public.set_updated_at();

-- SECURITY DEFINER with a fixed search_path so these can read `profiles` even
-- though `profiles` has RLS enabled. Without it, a policy calling app_role()
-- would re-enter the same policy it is evaluating.
create or replace function public.app_role()
returns text
language sql
security definer
stable
set search_path = public
as $$
  select role from public.profiles where id = unibuddy_auth.user_id();
$$;

create or replace function public.app_campus_id()
returns uuid
language sql
security definer
stable
set search_path = public
as $$
  select campus_id from public.profiles where id = unibuddy_auth.user_id();
$$;

create or replace function public.app_department_id()
returns uuid
language sql
security definer
stable
set search_path = public
as $$
  select department_id from public.profiles where id = unibuddy_auth.user_id();
$$;

create or replace function public.app_cross_campus_records()
returns boolean
language sql
security definer
stable
set search_path = public
as $$
  select coalesce(
    (select cross_campus_record_access from public.profiles where id = unibuddy_auth.user_id()),
    false
  );
$$;

revoke execute on function public.app_role() from public, anon;
revoke execute on function public.app_campus_id() from public, anon;
revoke execute on function public.app_department_id() from public, anon;
revoke execute on function public.app_cross_campus_records() from public, anon;
grant execute on function public.app_role() to authenticated, service_role;
grant execute on function public.app_campus_id() to authenticated, service_role;
grant execute on function public.app_department_id() to authenticated, service_role;
grant execute on function public.app_cross_campus_records() to authenticated, service_role;

alter table public.profiles enable row level security;

-- Own profile always. Faculty and authority see profiles in their own campus.
-- Individual profiles from other campuses need the explicit
-- cross_campus_record_access grant. Analytics never read this table directly.
create policy "profiles_select" on public.profiles
  for select to authenticated
  using (
    id = unibuddy_auth.user_id()
    or public.app_cross_campus_records()
    or (
      public.app_role() in ('faculty', 'authority')
      and campus_id = public.app_campus_id()
    )
  );

grant select on public.profiles to authenticated;
-- The backend's /auth/me lookup runs with the secret key as service_role.
-- Only SELECT is granted; profile writes stay out of the API for now.
grant select on public.profiles to service_role;
