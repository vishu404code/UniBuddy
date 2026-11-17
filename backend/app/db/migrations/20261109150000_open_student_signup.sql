-- Open Student signup. A verified Google person with no profile becomes a Student.
--
-- Only the backend (service_role) can call this. It can create only a 'student' profile, with no
-- campus and no department, so it never grants a privileged role. It refuses if the account or the
-- email already has a profile. Faculty, Authority and Management are still created only by authorized
-- provisioning.

create or replace function public.open_student_signup(p_account uuid, p_email text, p_full_name text)
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
  values (p_account, lower(p_email), nullif(trim(coalesce(p_full_name, '')), ''), 'student', null, null, false);
  return jsonb_build_object('id', p_account, 'role', 'student');
end;
$$;

revoke execute on function public.open_student_signup(uuid, text, text) from public, anon, authenticated;
grant execute on function public.open_student_signup(uuid, text, text) to service_role;
