-- Faculty may create and publish university-wide documents, as Authority may. Students still may not.
-- Replaces the trigger function from 20261109140000_university_scope_guard.sql. The trigger itself is unchanged.
create or replace function public.enforce_university_scope_uploader()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  uploader_role text;
begin
  if new.scope = 'university_wide' then
    select role into uploader_role from public.profiles where id = new.uploaded_by;
    if uploader_role is distinct from 'authority'
       and uploader_role is distinct from 'faculty'
       and uploader_role is distinct from 'super_admin' then
      raise exception 'university_wide_requires_staff' using errcode = '42501';
    end if;
  end if;
  return new;
end;
$$;

revoke execute on function public.enforce_university_scope_uploader() from public, anon, authenticated, service_role;
