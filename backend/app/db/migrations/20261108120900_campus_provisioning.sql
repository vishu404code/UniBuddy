-- GENERATED from supabase/migrations/20261108120900_campus_provisioning.sql by tools/port_supabase_migrations.py. Do not edit by hand.
-- Campus-scoped user provisioning and its audit trail.
--
-- An authority user onboards students and faculty for their own campus only. The
-- campus always comes from the actor's profile, never from the caller's input.
-- Only the service_role key can execute these functions. It gets no direct insert
-- on profiles, so every rule below is enforced in the database too.

create table public.provisioning_audit (
  id uuid primary key default gen_random_uuid(),
  actor_id uuid not null references public.profiles(id),
  actor_campus_id uuid references public.campuses(id),
  target_email text not null,
  target_user_id uuid,
  -- Wider than the roles this API provisions, so rejected attempts for other roles are recorded.
  target_role text not null check (target_role in ('student', 'faculty', 'authority', 'management')),
  campus_id uuid references public.campuses(id),
  department_id uuid,
  outcome text not null check (outcome in ('invited', 'rejected', 'failed', 'compensated')),
  reason text,
  created_at timestamptz not null default now()
);

create index provisioning_audit_actor_idx on public.provisioning_audit (actor_id, created_at desc);
create index provisioning_audit_email_idx on public.provisioning_audit (target_email);

-- No policies and no grants to anon or authenticated: the audit trail is written and
-- read only through the functions below and by the database owner.
alter table public.provisioning_audit enable row level security;
revoke all on public.provisioning_audit from anon, authenticated, service_role;

create or replace function public.provisioning_precheck(
  p_actor uuid,
  p_email text,
  p_role text,
  p_department uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  actor_role text;
  actor_campus uuid;
  reason text;
begin
  select role, campus_id into actor_role, actor_campus from public.profiles where id = p_actor;

  if actor_role is distinct from 'authority' then
    reason := 'not_authority';
  elsif actor_campus is null then
    reason := 'no_campus';
  elsif p_role not in ('student', 'faculty') then
    reason := 'invalid_role';
  elsif p_role = 'faculty' and p_department is null then
    reason := 'department_required';
  elsif p_department is not null and not exists (
          select 1 from public.departments d
           where d.id = p_department and d.campus_id = actor_campus) then
    reason := 'department_not_in_campus';
  elsif exists (select 1 from public.profiles where email = lower(p_email)) then
    reason := 'email_exists';
  end if;

  if reason is not null then
    insert into public.provisioning_audit
      (actor_id, actor_campus_id, target_email, target_role, campus_id, department_id, outcome, reason)
    values
      (p_actor, actor_campus, lower(p_email),
       case when p_role in ('student', 'faculty', 'authority', 'management') then p_role else 'student' end,
       actor_campus, p_department, 'rejected', reason);
    return jsonb_build_object('ok', false, 'reason', reason);
  end if;

  return jsonb_build_object('ok', true, 'campus_id', actor_campus);
end;
$$;

create or replace function public.provisioning_complete(
  p_actor uuid,
  p_user_id uuid,
  p_email text,
  p_full_name text,
  p_role text,
  p_department uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  actor_role text;
  actor_campus uuid;
  created public.profiles;
begin
  select role, campus_id into actor_role, actor_campus from public.profiles where id = p_actor;
  if actor_role is distinct from 'authority' or actor_campus is null then
    raise exception 'provisioning_not_permitted' using errcode = 'P0001';
  end if;
  if p_role not in ('student', 'faculty') then
    raise exception 'provisioning_invalid_role' using errcode = 'P0001';
  end if;
  if p_department is not null and not exists (
       select 1 from public.departments d where d.id = p_department and d.campus_id = actor_campus) then
    raise exception 'provisioning_department_not_in_campus' using errcode = 'P0001';
  end if;

  insert into public.profiles (id, email, full_name, role, campus_id, department_id, cross_campus_record_access)
  values (p_user_id, lower(p_email), p_full_name, p_role, actor_campus, p_department, false)
  returning * into created;

  insert into public.provisioning_audit
    (actor_id, actor_campus_id, target_email, target_user_id, target_role, campus_id, department_id, outcome)
  values
    (p_actor, actor_campus, lower(p_email), p_user_id, p_role, actor_campus, p_department, 'invited');

  return jsonb_build_object(
    'id', created.id, 'email', created.email, 'full_name', created.full_name,
    'role', created.role, 'campus_id', created.campus_id, 'department_id', created.department_id
  );
end;
$$;

create or replace function public.provisioning_record_failure(
  p_actor uuid,
  p_email text,
  p_role text,
  p_department uuid,
  p_outcome text,
  p_reason text,
  p_user_id uuid default null
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  actor_campus uuid;
begin
  if p_outcome not in ('failed', 'compensated') then
    raise exception 'provisioning_invalid_outcome' using errcode = 'P0001';
  end if;
  select campus_id into actor_campus from public.profiles where id = p_actor;
  insert into public.provisioning_audit
    (actor_id, actor_campus_id, target_email, target_user_id, target_role, campus_id, department_id, outcome, reason)
  values
    (p_actor, actor_campus, lower(p_email), p_user_id, coalesce(p_role, 'student'), actor_campus, p_department, p_outcome, p_reason);
end;
$$;

revoke execute on function public.provisioning_precheck(uuid, text, text, uuid) from public, anon, authenticated;
revoke execute on function public.provisioning_complete(uuid, uuid, text, text, text, uuid) from public, anon, authenticated;
revoke execute on function public.provisioning_record_failure(uuid, text, text, uuid, text, text, uuid) from public, anon, authenticated;
grant execute on function public.provisioning_precheck(uuid, text, text, uuid) to service_role;
grant execute on function public.provisioning_complete(uuid, uuid, text, text, text, uuid) to service_role;
grant execute on function public.provisioning_record_failure(uuid, text, text, uuid, text, text, uuid) to service_role;
