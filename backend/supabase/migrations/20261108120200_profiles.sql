-- Profiles (roles, campus, department) and the RLS helper functions that
-- policies in later migrations depend on.
--
-- Profiles are not created by a signup trigger: role and campus are assigned
-- by the backend using the service_role key. Self-selected roles or campuses
-- at signup would let anyone grant themselves staff access.

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null unique,
  full_name text,
  role text not null default 'student'
    check (role in ('student', 'faculty', 'authority', 'management')),
  campus_id uuid references public.campuses(id),
  department_id uuid,
  -- Flexible extra fields the frontend's onboarding already collects
  -- (e.g. course, age) without forcing a schema change for each one.
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint profiles_department_in_campus
    foreign key (department_id, campus_id)
    references public.departments(id, campus_id),
  constraint profiles_department_requires_campus
    check (department_id is null or campus_id is not null)
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
  select role from public.profiles where id = auth.uid();
$$;

create or replace function public.app_campus_id()
returns uuid
language sql
security definer
stable
set search_path = public
as $$
  select campus_id from public.profiles where id = auth.uid();
$$;

create or replace function public.app_department_id()
returns uuid
language sql
security definer
stable
set search_path = public
as $$
  select department_id from public.profiles where id = auth.uid();
$$;

revoke execute on function public.app_role() from public, anon;
revoke execute on function public.app_campus_id() from public, anon;
revoke execute on function public.app_department_id() from public, anon;
grant execute on function public.app_role() to authenticated, service_role;
grant execute on function public.app_campus_id() to authenticated, service_role;
grant execute on function public.app_department_id() to authenticated, service_role;

alter table public.profiles enable row level security;

-- Own profile always; authority and management see all profiles; faculty see
-- profiles in their own campus only (campus limits personal-data access here;
-- it does not limit document retrieval).
create policy "profiles_select" on public.profiles
  for select to authenticated
  using (
    id = auth.uid()
    or public.app_role() in ('authority', 'management')
    or (public.app_role() = 'faculty' and campus_id = public.app_campus_id())
  );

grant select on public.profiles to authenticated;
