-- Courses, academic metadata and targeted announcements.
--
-- Additive and backward-compatible: every new column is nullable, existing rows keep null
-- metadata, and an announcement with no targeting fields and no selected people is visible
-- exactly as before.
--
-- Courses are per campus. Only the backend (secret key) writes them: Authority creates, renames
-- and removes courses; Faculty and Authority can only select active courses. A course that is
-- already referenced is deactivated, never hard-deleted (the backend checks before deleting).
--
-- Targeting for an all_students announcement:
--   - no filters and no selected people  -> every student (unchanged behaviour)
--   - filters (year, batch, course, section) -> students whose profile matches each filter that is set
--   - selected people                    -> those students, plus any filter matches
-- Staff visibility is unchanged: faculty and authority see the announcements of their campus
-- (or university-wide ones), targeted or not.

-- 1. Courses -----------------------------------------------------------------------------

create table public.courses (
  id uuid primary key default gen_random_uuid(),
  campus_id uuid not null references public.campuses(id) on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 80),
  active boolean not null default true,
  created_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  -- Target of composite foreign keys that keep a course on the same campus as the record that uses it.
  constraint courses_id_campus_key unique (id, campus_id)
);

-- Case-insensitive: "BBA" and "bba" are the same course on a campus.
create unique index courses_campus_name_key on public.courses (campus_id, lower(btrim(name)));

create trigger courses_set_updated_at
  before update on public.courses
  for each row execute function public.set_updated_at();

alter table public.courses enable row level security;

create policy "courses_select_own_campus" on public.courses
  for select to authenticated
  using (campus_id = public.app_campus_id());

grant select on public.courses to authenticated;

-- 2. Student academic fields on profiles (set by the backend only) -----------------------

alter table public.profiles
  add column academic_year text check (academic_year is null or char_length(academic_year) between 1 and 20),
  add column batch_year integer check (batch_year is null or batch_year between 2000 and 2100),
  add column section text check (section is null or char_length(section) between 1 and 10),
  add column course_id uuid,
  add constraint profiles_course_in_campus
    foreign key (course_id, campus_id) references public.courses (id, campus_id),
  add constraint profiles_course_requires_campus
    check (course_id is null or campus_id is not null);

-- 3. Documents: academic metadata for browsing and filtering -----------------------------
-- These fields never widen access. Document access stays with can_read_document().

alter table public.documents
  add column academic_year text check (academic_year is null or char_length(academic_year) between 1 and 20),
  add column batch_year integer check (batch_year is null or batch_year between 2000 and 2100),
  add column section text check (section is null or char_length(section) between 1 and 10),
  add column course_id uuid,
  add column source_person text check (source_person is null or char_length(source_person) between 1 and 120),
  add constraint documents_course_in_campus
    foreign key (course_id, campus_id) references public.courses (id, campus_id),
  add constraint documents_course_requires_campus
    check (course_id is null or campus_id is not null);

create index documents_course_id_idx on public.documents (course_id);

-- 4. Announcements: targeting fields and selected people ---------------------------------

alter table public.announcements
  add column academic_year text check (academic_year is null or char_length(academic_year) between 1 and 20),
  add column batch_year integer check (batch_year is null or batch_year between 2000 and 2100),
  add column section text check (section is null or char_length(section) between 1 and 10),
  add column course_id uuid,
  add constraint announcements_course_in_campus
    foreign key (course_id, campus_id) references public.courses (id, campus_id),
  add constraint announcements_course_requires_campus
    check (course_id is null or campus_id is not null);

create index announcements_course_id_idx on public.announcements (course_id);

create table public.announcement_recipients (
  announcement_id uuid not null references public.announcements(id) on delete cascade,
  profile_id uuid not null references public.profiles(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (announcement_id, profile_id)
);

create index announcement_recipients_profile_id_idx on public.announcement_recipients (profile_id);

-- Only the server reads or writes recipients. The visibility function below reads them.
alter table public.announcement_recipients enable row level security;
revoke all on public.announcement_recipients from anon, authenticated;
grant select, insert, delete on public.announcement_recipients to service_role;

-- True when the signed-in user may see an all_students announcement. Runs as its owner so it can
-- read profiles and recipients, which callers cannot read directly.
create or replace function public.announcement_visible_to_me(a public.announcements)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  with has_filters as (
    select (a.academic_year is not null or a.batch_year is not null
            or a.course_id is not null or a.section is not null) as value
  ),
  has_people as (
    select exists (
      select 1 from public.announcement_recipients r where r.announcement_id = a.id
    ) as value
  ),
  i_am_selected as (
    select exists (
      select 1 from public.announcement_recipients r
      where r.announcement_id = a.id and r.profile_id = unibuddy_auth.user_id()
    ) as value
  ),
  filters_match as (
    select exists (
      select 1 from public.profiles p
      where p.id = unibuddy_auth.user_id()
        -- A campus-scoped announcement reaches only its own campus when filters are used.
        and (a.scope = 'university_wide' or p.campus_id = a.campus_id)
        and (a.academic_year is null or a.academic_year = p.academic_year)
        and (a.batch_year is null or a.batch_year = p.batch_year)
        and (a.course_id is null or a.course_id = p.course_id)
        and (a.section is null or a.section = p.section)
    ) as value
  )
  select
    (not (select value from has_filters) and not (select value from has_people))
    or (select value from i_am_selected)
    or ((select value from has_filters) and (select value from filters_match));
$$;

revoke execute on function public.announcement_visible_to_me(public.announcements) from public, anon;
grant execute on function public.announcement_visible_to_me(public.announcements) to authenticated, service_role;

alter policy announcements_select on public.announcements using (
  (audience = 'all_students' and public.announcement_visible_to_me(announcements))
  or ((select public.app_role()) in ('faculty', 'authority')
      and (scope = 'university_wide' or campus_id = (select public.app_campus_id())))
);
