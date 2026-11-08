-- Only authority (and Super Admin) may create, publish or archive university-wide documents.
-- Faculty cannot set scope to university_wide, so they can never publish one. The API checks the
-- same rule; this trigger makes the database refuse it even if the API is bypassed.

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
    if uploader_role is distinct from 'authority' and uploader_role is distinct from 'super_admin' then
      raise exception 'university_wide_requires_authority' using errcode = '42501';
    end if;
  end if;
  return new;
end;
$$;

revoke execute on function public.enforce_university_scope_uploader() from public, anon, authenticated, service_role;

create trigger documents_university_scope_guard
  before insert or update of scope, uploaded_by on public.documents
  for each row execute function public.enforce_university_scope_uploader();
