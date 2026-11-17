-- Pre-authorized Faculty sign-up. The backend (app/services/google_sign_in.py) decides which verified
-- Google emails qualify; this function only writes the profile. Like open_student_signup, it is
-- callable by service_role only, so no browser or signed-in user can reach it.
--
-- It creates a Faculty profile with a campus and never a department, and it refuses to overwrite
-- an existing profile. Roles still never come from the browser or from Google.

create or replace function public.open_preauthorized_faculty_signup(
  p_account uuid,
  p_email text,
  p_full_name text,
  p_campus uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_account is null or p_email is null or length(trim(p_email)) = 0 or p_campus is null then
    raise exception 'invalid_account' using errcode = 'P0001';
  end if;
  if not exists (select 1 from public.campuses where id = p_campus) then
    raise exception 'campus_not_found' using errcode = 'P0001';
  end if;
  if exists (select 1 from public.profiles where id = p_account)
     or exists (select 1 from public.profiles where email = lower(p_email)) then
    raise exception 'profile_exists' using errcode = 'P0001';
  end if;
  insert into public.profiles (id, email, full_name, role, campus_id, department_id, cross_campus_record_access)
  values (p_account, lower(p_email), nullif(trim(coalesce(p_full_name, '')), ''), 'faculty', p_campus, null, false);
  return jsonb_build_object('id', p_account, 'role', 'faculty');
end;
$$;

revoke execute on function public.open_preauthorized_faculty_signup(uuid, text, text, uuid) from public, anon, authenticated;
grant execute on function public.open_preauthorized_faculty_signup(uuid, text, text, uuid) to service_role;
