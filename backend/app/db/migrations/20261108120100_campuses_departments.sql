-- GENERATED from supabase/migrations/20261108120100_campuses_departments.sql by tools/port_supabase_migrations.py. Do not edit by hand.
-- Campuses and departments.
-- Campus/department matter for user assignment, ticket routing, and
-- reporting -- NOT for restricting which documents a student can retrieve.

create table public.campuses (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  code text not null unique,
  created_at timestamptz not null default now()
);

create table public.departments (
  id uuid primary key default gen_random_uuid(),
  campus_id uuid not null references public.campuses(id) on delete cascade,
  name text not null,
  created_at timestamptz not null default now(),
  unique (campus_id, name),
  -- Target of composite foreign keys that guarantee a department belongs to
  -- the campus recorded alongside it on users, documents, tickets, announcements.
  unique (id, campus_id)
);

create index departments_campus_id_idx on public.departments(campus_id);

alter table public.campuses enable row level security;
alter table public.departments enable row level security;

-- Reference data: any authenticated user can read it (dropdowns, routing).
-- No INSERT/UPDATE/DELETE policy is defined -- those happen via the backend
-- using the secret key, which bypasses RLS entirely.
create policy "campuses_select_authenticated" on public.campuses
  for select to authenticated using (true);

create policy "departments_select_authenticated" on public.departments
  for select to authenticated using (true);

-- No anon grants: the Data API does not expose these tables to anon.
grant usage on schema public to authenticated, service_role;
grant select on public.campuses to authenticated;
grant select on public.departments to authenticated;
