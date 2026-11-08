\set ON_ERROR_STOP on
-- Fixtures (as postgres). Actors: authority c1, authority c2, management, student, faculty.
insert into auth.users (id) values
 ('20000000-0000-4000-8000-000000000001'),('20000000-0000-4000-8000-000000000002'),
 ('20000000-0000-4000-8000-000000000003'),('20000000-0000-4000-8000-000000000004'),
 ('20000000-0000-4000-8000-000000000005');
-- The invite creates the auth user before the profile is completed.
insert into auth.users (id) values ('30000000-0000-4000-8000-000000000001');
insert into public.campuses (id, name, code) values
 ('c2000000-0000-4000-8000-000000000001','Prov Campus 1','pv1'),
 ('c2000000-0000-4000-8000-000000000002','Prov Campus 2','pv2');
insert into public.departments (id, campus_id, name) values
 ('d2000000-0000-4000-8000-000000000001','c2000000-0000-4000-8000-000000000001','Prov CS'),
 ('d2000000-0000-4000-8000-000000000002','c2000000-0000-4000-8000-000000000002','Prov CS');
insert into public.profiles (id, email, role, campus_id, department_id) values
 ('20000000-0000-4000-8000-000000000001','auth1@x.test','authority','c2000000-0000-4000-8000-000000000001',null),
 ('20000000-0000-4000-8000-000000000002','auth2@x.test','authority','c2000000-0000-4000-8000-000000000002',null),
 ('20000000-0000-4000-8000-000000000003','mgmt@x.test','management','c2000000-0000-4000-8000-000000000001',null),
 ('20000000-0000-4000-8000-000000000004','stud@x.test','student','c2000000-0000-4000-8000-000000000001',null),
 ('20000000-0000-4000-8000-000000000005','fac@x.test','faculty','c2000000-0000-4000-8000-000000000001','d2000000-0000-4000-8000-000000000001');

set role service_role;

-- 1. Authority on campus 1 may onboard a student; the campus comes from the actor.
do $$ declare r jsonb; begin
  r := public.provisioning_precheck('20000000-0000-4000-8000-000000000001', 'new.student@x.test', 'student', null);
  assert (r->>'ok')::boolean, 'authority precheck should pass: ' || r::text;
  assert r->>'campus_id' = 'c2000000-0000-4000-8000-000000000001', 'campus must be the actor''s campus';
  raise notice 'PASS authority precheck passes with actor campus';
end $$;

-- 2. Rejections, each recorded in the audit trail.
do $$ declare r jsonb; begin
  r := public.provisioning_precheck('20000000-0000-4000-8000-000000000004', 'x1@x.test', 'student', null);
  assert r->>'reason' = 'not_authority', 'student actor must be rejected';
  r := public.provisioning_precheck('20000000-0000-4000-8000-000000000003', 'x2@x.test', 'student', null);
  assert r->>'reason' = 'not_authority', 'management actor must be rejected';
  r := public.provisioning_precheck('20000000-0000-4000-8000-000000000001', 'x3@x.test', 'faculty', 'd2000000-0000-4000-8000-000000000002');
  assert r->>'reason' = 'department_not_in_campus', 'department from another campus must be rejected';
  r := public.provisioning_precheck('20000000-0000-4000-8000-000000000001', 'x4@x.test', 'faculty', null);
  assert r->>'reason' = 'department_required', 'faculty need a department';
  r := public.provisioning_precheck('20000000-0000-4000-8000-000000000001', 'x5@x.test', 'authority', null);
  assert r->>'reason' = 'invalid_role', 'authority accounts cannot be provisioned here';
  r := public.provisioning_precheck('20000000-0000-4000-8000-000000000001', 'x6@x.test', 'management', null);
  assert r->>'reason' = 'invalid_role', 'management accounts cannot be provisioned here';
  r := public.provisioning_precheck('20000000-0000-4000-8000-000000000001', 'STUD@x.test', 'student', null);
  assert r->>'reason' = 'email_exists', 'existing email must be rejected, case-insensitively';
  raise notice 'PASS rejections are enforced';
end $$;

-- Audit rows are read as the owner: the service role is deliberately denied direct reads.
reset role;
do $$ begin
  assert (select count(*) from public.provisioning_audit where outcome = 'rejected') = 7, 'every rejection is audited';
  raise notice 'PASS every rejection is audited';
end $$;
set role service_role;

-- 3. Completion creates the profile with the actor's campus, never a caller-chosen one.
do $$ declare created jsonb; begin
  created := public.provisioning_complete('20000000-0000-4000-8000-000000000001', '30000000-0000-4000-8000-000000000001',
                                          'new.student@x.test', 'New Student', 'student', null);
  assert created->>'campus_id' = 'c2000000-0000-4000-8000-000000000001', 'completion must use the actor campus';
  assert (select cross_campus_record_access from public.profiles where id = '30000000-0000-4000-8000-000000000001') = false, 'no cross-campus grant on provisioning';
  raise notice 'PASS completion uses actor campus';
end $$;

reset role;
do $$ begin
  assert (select count(*) from public.provisioning_audit where outcome = 'invited') = 1, 'completion is audited';
  raise notice 'PASS completion is audited';
end $$;
set role service_role;

-- 4. Completion re-checks the rules inside the database.
do $$ declare caught text; begin
  caught := null;
  begin
    perform public.provisioning_complete('20000000-0000-4000-8000-000000000001', '30000000-0000-4000-8000-000000000002',
                                         'bad@x.test', 'Bad', 'management', null);
  exception when others then caught := sqlerrm; end;
  assert caught = 'provisioning_invalid_role', 'management role must be refused at completion: ' || coalesce(caught, 'none');

  caught := null;
  begin
    perform public.provisioning_complete('20000000-0000-4000-8000-000000000001', '30000000-0000-4000-8000-000000000003',
                                         'bad2@x.test', 'Bad', 'faculty', 'd2000000-0000-4000-8000-000000000002');
  exception when others then caught := sqlerrm; end;
  assert caught = 'provisioning_department_not_in_campus', 'cross-campus department refused at completion';

  caught := null;
  begin
    perform public.provisioning_complete('20000000-0000-4000-8000-000000000004', '30000000-0000-4000-8000-000000000004',
                                         'bad3@x.test', 'Bad', 'student', null);
  exception when others then caught := sqlerrm; end;
  assert caught = 'provisioning_not_permitted', 'student cannot complete provisioning';
  raise notice 'PASS completion re-checks rules';
end $$;

-- 5. Failure records for compensation paths.
select public.provisioning_record_failure('20000000-0000-4000-8000-000000000001', 'new2@x.test', 'student', null,
                                          'compensated', 'profile insert failed', '30000000-0000-4000-8000-000000000005');
do $$ declare caught text; begin
  caught := null;
  begin
    perform public.provisioning_record_failure('20000000-0000-4000-8000-000000000001', 'x@x.test', 'student', null,
                                               'invited', 'not a failure');
  exception when others then caught := sqlerrm; end;
  assert caught = 'provisioning_invalid_outcome', 'only failed or compensated may be recorded this way';
  raise notice 'PASS failure records';
end $$;
reset role;

-- 6. Privileges: only service_role may call the functions; the audit trail is closed to API roles.
do $$ declare caught text; begin
  caught := null;
  begin
    set local role authenticated;
    perform public.provisioning_precheck('20000000-0000-4000-8000-000000000001', 'p@x.test', 'student', null);
  exception when others then caught := sqlstate; end;
  assert caught = '42501', 'authenticated must not call provisioning functions: ' || coalesce(caught, 'none');
  reset role;

  caught := null;
  begin
    set local role anon;
    perform public.provisioning_precheck('20000000-0000-4000-8000-000000000001', 'p@x.test', 'student', null);
  exception when others then caught := sqlstate; end;
  assert caught = '42501', 'anon must not call provisioning functions';
  reset role;

  caught := null;
  begin
    set local role service_role;
    insert into public.profiles (id, email, role) values ('30000000-0000-4000-8000-000000000009', 'direct@x.test', 'student');
  exception when others then caught := sqlstate; end;
  assert caught = '42501', 'service_role must not insert profiles directly';
  reset role;

  caught := null;
  begin
    set local role service_role;
    perform count(*) from public.provisioning_audit;
  exception when others then caught := sqlstate; end;
  assert caught = '42501', 'service_role must not read the audit table directly';
  reset role;
  raise notice 'PASS privileges';
end $$;
