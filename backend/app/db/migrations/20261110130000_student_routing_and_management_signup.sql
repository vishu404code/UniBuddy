-- Ticket department is optional. A question sent without a department goes to the campus queue,
-- which Authority sees under the existing campus rule. Faculty still see only their own department.
alter table public.tickets alter column department_id drop not null;

-- A new Student's campus is set by the database, and only when the Student has none. The backend
-- cannot update profiles directly (service_role has no UPDATE on profiles), so it calls this instead.
create or replace function public.assign_campus_to_student(p_account uuid, p_campus uuid)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.profiles
     set campus_id = p_campus
   where id = p_account
     and role = 'student'
     and campus_id is null
     and exists (select 1 from public.campuses c where c.id = p_campus);
  return found;
end;
$$;

revoke execute on function public.assign_campus_to_student(uuid, uuid) from public, anon, authenticated;
grant execute on function public.assign_campus_to_student(uuid, uuid) to service_role;

-- Pre-authorized Management sign-up. Only the backend calls it, for one verified email it already
-- checked. Management has no campus and no department. It never creates a Student profile.
create or replace function public.open_preauthorized_management_signup(
  p_account uuid,
  p_email text,
  p_full_name text
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_account is null or p_email is null or length(trim(p_email)) = 0 then
    raise exception 'invalid_account' using errcode = 'P0001';
  end if;
  if exists (select 1 from public.profiles where id = p_account)
     or exists (select 1 from public.profiles where email = lower(p_email)) then
    raise exception 'profile_exists' using errcode = 'P0001';
  end if;
  insert into public.profiles (id, email, full_name, role, campus_id, department_id, cross_campus_record_access)
  values (p_account, lower(p_email), nullif(trim(coalesce(p_full_name, '')), ''), 'management', null, null, false);
  return jsonb_build_object('id', p_account, 'role', 'management');
end;
$$;

revoke execute on function public.open_preauthorized_management_signup(uuid, text, text) from public, anon, authenticated;
grant execute on function public.open_preauthorized_management_signup(uuid, text, text) to service_role;
