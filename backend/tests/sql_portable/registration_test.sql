-- GENERATED from tests/sql/registration_test.sql by tools/port_supabase_migrations.py. Do not edit by hand.
\set ON_ERROR_STOP on
-- Registration requests: the table grants nothing by itself, and only the server can write it.
set role service_role;
insert into public.registration_requests (email, full_name) values ('student.one@nst.rishihood.edu.in', 'Student One');
do $$ declare caught text; begin
  caught := null;
  begin
    insert into public.registration_requests (email, full_name) values ('student.one@nst.rishihood.edu.in', 'Again');
  exception when unique_violation then caught := 'duplicate';
  end;
  assert caught = 'duplicate', 'a second pending request for the same address must be refused';
  raise notice 'PASS one pending request per address';
end $$;
insert into public.registration_requests (email, full_name, status) values ('student.two@nst.rishihood.edu.in', 'Student Two', 'rejected');
insert into public.registration_requests (email, full_name, status) values ('student.two@nst.rishihood.edu.in', 'Student Two', 'pending');
do $$ declare caught text; begin
  caught := null;
  begin
    insert into public.registration_requests (email, full_name) values ('Mixed.Case@nst.rishihood.edu.in', 'Bad');
  exception when check_violation then caught := 'check';
  end;
  assert caught = 'check', 'emails must be stored lowercase';
  raise notice 'PASS emails stored lowercase';
end $$;
reset role;

do $$ declare caught text; begin
  caught := null;
  begin
    set local role authenticated;
    perform count(*) from public.registration_requests;
  exception when insufficient_privilege then caught := 'denied';
  end;
  assert caught = 'denied', 'authenticated must not read registration requests';
  reset role;

  caught := null;
  begin
    set local role anon;
    insert into public.registration_requests (email, full_name) values ('anon@nst.rishihood.edu.in', 'Anon');
  exception when insufficient_privilege then caught := 'denied';
  end;
  assert caught = 'denied', 'anon must not insert registration requests';
  reset role;
  raise notice 'PASS API roles cannot read or write registration requests';
end $$;
