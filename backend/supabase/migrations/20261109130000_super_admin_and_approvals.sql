-- Super Admin: account provisioning only. It is never created through the API.
-- Also: super-admin provisioning for authority and management accounts, and an account
-- list that exposes no academic records.

alter table public.profiles drop constraint profiles_role_check;
alter table public.profiles add constraint profiles_role_check
  check (role in ('student', 'faculty', 'authority', 'management', 'super_admin'));

alter table public.provisioning_audit drop constraint provisioning_audit_target_role_check;
alter table public.provisioning_audit add constraint provisioning_audit_target_role_check
  check (target_role in ('student', 'faculty', 'authority', 'management', 'super_admin'));

-- One-time bootstrap. Run from the database owner's session (SQL editor or CLI) after the
-- Super Admin's auth user has been invited. It refuses a second Super Admin, and it only
-- accepts the exact university domain. No API role can execute it.
create or replace function public.bootstrap_super_admin(p_user_id uuid, p_email text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
begin
  if exists (select 1 from public.profiles where role = 'super_admin') then
    raise exception 'super_admin_already_exists' using errcode = 'P0001';
  end if;
  if split_part(lower(p_email), '@', 2) <> 'nst.rishihood.edu.in' then
    raise exception 'email_domain_not_allowed' using errcode = 'P0001';
  end if;
  if not exists (select 1 from auth.users where id = p_user_id) then
    raise exception 'auth_user_not_found' using errcode = 'P0001';
  end if;

  insert into public.profiles (id, email, full_name, role, campus_id, cross_campus_record_access)
  values (p_user_id, lower(p_email), 'Super Admin', 'super_admin', null, false);

  insert into public.provisioning_audit
    (actor_id, target_email, target_user_id, target_role, outcome, reason)
  values
    (p_user_id, lower(p_email), p_user_id, 'super_admin', 'invited', 'super_admin_bootstrap');

  return jsonb_build_object('id', p_user_id, 'role', 'super_admin');
end;
$$;

revoke execute on function public.bootstrap_super_admin(uuid, text) from public, anon, authenticated, service_role;

-- Super Admin provisioning: authority (campus required) and management (campus optional).
create or replace function public.super_admin_provision_precheck(
  p_actor uuid,
  p_email text,
  p_role text,
  p_campus uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  actor_role text;
  reason text;
begin
  select role into actor_role from public.profiles where id = p_actor;

  if actor_role is distinct from 'super_admin' then
    reason := 'not_super_admin';
  elsif p_role not in ('authority', 'management') then
    reason := 'invalid_role';
  elsif p_role = 'authority' and p_campus is null then
    reason := 'campus_required';
  elsif p_campus is not null and not exists (select 1 from public.campuses where id = p_campus) then
    reason := 'campus_not_found';
  elsif exists (select 1 from public.profiles where email = lower(p_email)) then
    reason := 'email_exists';
  end if;

  if reason is not null then
    insert into public.provisioning_audit
      (actor_id, target_email, target_role, campus_id, outcome, reason)
    values
      (p_actor, lower(p_email),
       case when p_role in ('student', 'faculty', 'authority', 'management') then p_role else 'student' end,
       p_campus, 'rejected', reason);
    return jsonb_build_object('ok', false, 'reason', reason);
  end if;

  return jsonb_build_object('ok', true);
end;
$$;

create or replace function public.super_admin_provision_complete(
  p_actor uuid,
  p_user_id uuid,
  p_email text,
  p_full_name text,
  p_role text,
  p_campus uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  actor_role text;
  created public.profiles;
begin
  select role into actor_role from public.profiles where id = p_actor;
  if actor_role is distinct from 'super_admin' then
    raise exception 'provisioning_not_permitted' using errcode = 'P0001';
  end if;
  if p_role not in ('authority', 'management') then
    raise exception 'provisioning_invalid_role' using errcode = 'P0001';
  end if;
  if p_role = 'authority' and p_campus is null then
    raise exception 'provisioning_campus_required' using errcode = 'P0001';
  end if;
  if p_campus is not null and not exists (select 1 from public.campuses where id = p_campus) then
    raise exception 'provisioning_campus_not_found' using errcode = 'P0001';
  end if;

  insert into public.profiles (id, email, full_name, role, campus_id, department_id, cross_campus_record_access)
  values (p_user_id, lower(p_email), p_full_name, p_role, p_campus, null, false)
  returning * into created;

  insert into public.provisioning_audit
    (actor_id, target_email, target_user_id, target_role, campus_id, outcome)
  values
    (p_actor, lower(p_email), p_user_id, p_role, p_campus, 'invited');

  return jsonb_build_object(
    'id', created.id, 'email', created.email, 'full_name', created.full_name,
    'role', created.role, 'campus_id', created.campus_id, 'department_id', created.department_id
  );
end;
$$;

revoke execute on function public.super_admin_provision_precheck(uuid, text, text, uuid) from public, anon, authenticated;
revoke execute on function public.super_admin_provision_complete(uuid, uuid, text, text, text, uuid) from public, anon, authenticated;
grant execute on function public.super_admin_provision_precheck(uuid, text, text, uuid) to service_role;
grant execute on function public.super_admin_provision_complete(uuid, uuid, text, text, text, uuid) to service_role;

-- Account list for the Super Admin screen. Account fields only, no academic records.
-- The caller's own role is checked in the database, so the check cannot be skipped by the API.
create or replace function public.super_admin_list_accounts()
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
begin
  if public.app_role() is distinct from 'super_admin' then
    raise exception 'not_permitted' using errcode = '42501';
  end if;
  return (
    select coalesce(jsonb_agg(jsonb_build_object(
             'id', p.id, 'email', p.email, 'full_name', p.full_name, 'role', p.role,
             'campus_id', p.campus_id, 'campus_name', c.name, 'created_at', p.created_at
           ) order by p.created_at desc), '[]'::jsonb)
      from public.profiles p
      left join public.campuses c on c.id = p.campus_id
  );
end;
$$;

revoke execute on function public.super_admin_list_accounts() from public, anon;
grant execute on function public.super_admin_list_accounts() to authenticated;
