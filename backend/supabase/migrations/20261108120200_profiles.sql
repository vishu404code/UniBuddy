-- Milestone 2: profiles (roles) and the RLS helper functions every later
-- policy depends on.
--
-- Open question (see Milestone 2 report): this migration does NOT add a
-- trigger to auto-create a profile row on signup, because how
-- faculty/authority/management accounts actually get provisioned (self-serve
-- vs. admin/invite-only) hasn't been decided yet. For now, profile rows are
-- created and role/campus assigned by the backend using the service_role
-- key, which bypasses RLS -- not by end-user sessions.

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null unique,
  full_name text,
  role text not null default 'student'
    check (role in ('student', 'faculty', 'authority', 'management')),
  campus_id uuid references public.campuses(id),
  department_id uuid references public.departments(id),
  -- Flexible extra fields the frontend's onboarding already collects
  -- (e.g. course, age) without forcing a schema change for each one.
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index profiles_campus_id_idx on public.profiles(campus_id);
create index profiles_role_idx on public.profiles(role);

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute function public.set_updated_at();

-- SECURITY DEFINER + fixed search_path so these can read `profiles` even
-- though `profiles` itself has RLS enabled on it -- otherwise a policy that
-- calls app_role() would recurse into the same policy it's evaluating.
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

alter table public.profiles enable row level security;

-- A user can read their own profile; staff roles can read any profile
-- (needed, e.g., for faculty to see a student's info on a ticket).
create policy "profiles_select_self_or_staff" on public.profiles
  for select to authenticated
  using (
    id = auth.uid()
    or public.app_role() in ('faculty', 'authority', 'management')
  );

grant select on public.profiles to authenticated;
