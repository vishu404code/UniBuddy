\set ON_ERROR_STOP on
insert into auth.users (id) values
 ('60000000-0000-4000-8000-000000000001'),('60000000-0000-4000-8000-000000000002');
insert into public.campuses (id, name, code) values ('c6000000-0000-4000-8000-000000000001','Scope Campus','sc1');
insert into public.profiles (id, email, role, campus_id) values
 ('60000000-0000-4000-8000-000000000001','fac.scope@nst.rishihood.edu.in','faculty','c6000000-0000-4000-8000-000000000001'),
 ('60000000-0000-4000-8000-000000000002','auth.scope@nst.rishihood.edu.in','authority','c6000000-0000-4000-8000-000000000001');

-- 1. Faculty cannot insert a university-wide document.
do $$ declare caught text; begin
  caught := null;
  begin
    insert into public.documents (title, storage_path, uploaded_by, campus_id, scope)
    values ('x', 'p/x.pdf', '60000000-0000-4000-8000-000000000001', 'c6000000-0000-4000-8000-000000000001', 'university_wide');
  exception when sqlstate '42501' then caught := 'refused'; end;
  assert caught = 'refused', 'faculty must not create university-wide documents';
  raise notice 'PASS faculty cannot create university-wide documents';
end $$;

-- 2. Faculty cannot move an existing campus document to university-wide.
insert into public.documents (id, title, storage_path, uploaded_by, campus_id, scope)
values ('d6000000-0000-4000-8000-000000000001', 'campus doc', 'p/c.pdf', '60000000-0000-4000-8000-000000000001', 'c6000000-0000-4000-8000-000000000001', 'campus');
do $$ declare caught text; begin
  caught := null;
  begin
    update public.documents set scope = 'university_wide' where id = 'd6000000-0000-4000-8000-000000000001';
  exception when sqlstate '42501' then caught := 'refused'; end;
  assert caught = 'refused', 'scope change by faculty must be refused';
  raise notice 'PASS faculty cannot widen a campus document';
end $$;

-- 3. Authority can create one.
do $$ begin
  insert into public.documents (title, storage_path, uploaded_by, campus_id, scope)
  values ('authority notice', 'p/a.pdf', '60000000-0000-4000-8000-000000000002', 'c6000000-0000-4000-8000-000000000001', 'university_wide');
  raise notice 'PASS authority can create university-wide documents';
end $$;
