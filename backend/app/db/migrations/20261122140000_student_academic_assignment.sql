-- Authority-only assignment of a student's batch, section and course. PREPARED, NOT APPLIED.
--
-- Academic OPTIONS (batch years, sections) and COURSES already exist and are managed by Authority
-- (20261117100000, 20261117120000). This migration adds the missing piece: setting the values on a
-- STUDENT'S profile. Until now nothing could do that, so every profile had null academic fields.
--
-- Rules, enforced here in the database (the backend also checks, but this is the last line):
--   - the target must be a student on the same campus as the actor;
--   - the actor must be an authority of that campus (students and faculty cannot call this);
--   - each value must be an ACTIVE option or an ACTIVE course of that campus; null clears a field;
--   - every change is written to student_academic_audit with the values before and after.
-- Only the backend's service role may call the function. Browser roles cannot update profiles.

create table if not exists public.student_academic_audit (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references public.profiles(id) on delete cascade,
  changed_by uuid references public.profiles(id) on delete set null,
  changed_at timestamptz not null default now(),
  before_values jsonb not null,
  after_values jsonb not null
);

alter table public.student_academic_audit enable row level security;
revoke all on public.student_academic_audit from public, anon, authenticated;
grant select, insert on public.student_academic_audit to service_role;

create or replace function public.assign_student_academics(
  p_student uuid,
  p_actor uuid,
  p_batch_year integer,
  p_section text,
  p_course_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  st public.profiles%rowtype;
  before_values jsonb;
  after_values jsonb;
begin
  select * into st from public.profiles where id = p_student for update;
  if not found or st.role <> 'student' then
    raise exception 'student_not_found';
  end if;
  if st.campus_id is null then
    raise exception 'student_has_no_campus';
  end if;
  if not exists (
    select 1 from public.profiles a
     where a.id = p_actor and a.role = 'authority' and a.campus_id = st.campus_id
  ) then
    raise exception 'not_authorized';
  end if;

  if p_batch_year is not null and not exists (
    select 1 from public.filter_options o
     where o.campus_id = st.campus_id and o.kind = 'batch' and o.value = p_batch_year::text and o.active
  ) then
    raise exception 'batch_not_active';
  end if;
  if p_section is not null and not exists (
    select 1 from public.filter_options o
     where o.campus_id = st.campus_id and o.kind = 'section' and o.value = p_section and o.active
  ) then
    raise exception 'section_not_active';
  end if;
  if p_course_id is not null and not exists (
    select 1 from public.courses c
     where c.id = p_course_id and c.campus_id = st.campus_id and c.active
  ) then
    raise exception 'course_not_active';
  end if;

  before_values := jsonb_build_object('batch_year', st.batch_year, 'section', st.section, 'course_id', st.course_id);
  update public.profiles
     set batch_year = p_batch_year,
         section = p_section,
         course_id = p_course_id,
         updated_at = now()
   where id = p_student;
  after_values := jsonb_build_object('batch_year', p_batch_year, 'section', p_section, 'course_id', p_course_id);

  insert into public.student_academic_audit (student_id, changed_by, before_values, after_values)
  values (p_student, p_actor, before_values, after_values);
  return after_values;
end;
$$;

revoke execute on function public.assign_student_academics(uuid, uuid, integer, text, uuid) from public, anon, authenticated;
grant execute on function public.assign_student_academics(uuid, uuid, integer, text, uuid) to service_role;
