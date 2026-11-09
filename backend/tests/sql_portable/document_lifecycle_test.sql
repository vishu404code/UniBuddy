-- GENERATED from tests/sql/document_lifecycle_test.sql by tools/port_supabase_migrations.py. Do not edit by hand.
\set ON_ERROR_STOP on
-- Fixtures (as postgres, bypassing RLS)
insert into public.account_identities (id) values
 ('10000000-0000-4000-8000-000000000001'),  -- faculty c1
 ('10000000-0000-4000-8000-000000000002'),  -- authority c1
 ('10000000-0000-4000-8000-000000000003'),  -- authority c2
 ('10000000-0000-4000-8000-000000000004'),  -- student c1
 ('10000000-0000-4000-8000-000000000005');  -- management
insert into public.campuses (id, name, code) values
 ('c1000000-0000-4000-8000-000000000001','Campus 1','c1'),
 ('c1000000-0000-4000-8000-000000000002','Campus 2','c2');
insert into public.departments (id, campus_id, name) values
 ('d1000000-0000-4000-8000-000000000001','c1000000-0000-4000-8000-000000000001','CS'),
 ('d1000000-0000-4000-8000-000000000002','c1000000-0000-4000-8000-000000000002','CS');
insert into public.profiles (id, email, role, campus_id, department_id) values
 ('10000000-0000-4000-8000-000000000001','f1@x.test','faculty','c1000000-0000-4000-8000-000000000001','d1000000-0000-4000-8000-000000000001'),
 ('10000000-0000-4000-8000-000000000002','a1@x.test','authority','c1000000-0000-4000-8000-000000000001',null),
 ('10000000-0000-4000-8000-000000000003','a2@x.test','authority','c1000000-0000-4000-8000-000000000002',null),
 ('10000000-0000-4000-8000-000000000004','s1@x.test','student','c1000000-0000-4000-8000-000000000001',null),
 ('10000000-0000-4000-8000-000000000005','m@x.test','management','c1000000-0000-4000-8000-000000000001',null);
insert into public.conversations (id, user_id, title) values ('f1000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000004','c');
insert into public.messages (id, conversation_id, role, content) values
 ('f2000000-0000-4000-8000-000000000001','f1000000-0000-4000-8000-000000000001','user','q1'),
 ('f2000000-0000-4000-8000-000000000002','f1000000-0000-4000-8000-000000000001','user','q2');

-- Documents: two pending (c1), one ready draft (c1) and one published doc that the ready draft replaces.
insert into public.documents (id, title, storage_path, uploaded_by, campus_id, scope, visibility, publication_status, processing_status) values
 ('a1000000-0000-4000-8000-000000000001','pending A','p/a.pdf','10000000-0000-4000-8000-000000000001','c1000000-0000-4000-8000-000000000001','campus','public_students','draft','pending'),
 ('a1000000-0000-4000-8000-000000000002','pending B','p/b.pdf','10000000-0000-4000-8000-000000000001','c1000000-0000-4000-8000-000000000001','campus','public_students','draft','pending'),
 ('a1000000-0000-4000-8000-000000000003','old version','p/old.pdf','10000000-0000-4000-8000-000000000001','c1000000-0000-4000-8000-000000000001','campus','public_students','published','ready'),
 ('a1000000-0000-4000-8000-000000000004','new version','p/new.pdf','10000000-0000-4000-8000-000000000001','c1000000-0000-4000-8000-000000000001','campus','public_students','draft','ready');
update public.documents set replaces_document_id = 'a1000000-0000-4000-8000-000000000003' where id = 'a1000000-0000-4000-8000-000000000004';

-- Tickets: two in c1/CS (one assigned to faculty f1 and replied to), one unassigned in c1/CS, one in c2/CS.
insert into public.tickets (id, student_id, campus_id, department_id, assigned_faculty_id, subject, question, status, created_at) values
 ('e1000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000004','c1000000-0000-4000-8000-000000000001','d1000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001','t1','q','resolved', now() - interval '10 hours'),
 ('e1000000-0000-4000-8000-000000000002','10000000-0000-4000-8000-000000000004','c1000000-0000-4000-8000-000000000001','d1000000-0000-4000-8000-000000000001',null,'t2','q','submitted', now() - interval '3 hours'),
 ('e1000000-0000-4000-8000-000000000003','10000000-0000-4000-8000-000000000004','c1000000-0000-4000-8000-000000000002','d1000000-0000-4000-8000-000000000002',null,'t3','q','submitted', now() - interval '1 hour');
insert into public.ticket_events (ticket_id, actor_id, event_type, note, created_at) values
 ('e1000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001','reply','ok', now() - interval '5 hours');

-- 1. Claiming as service_role: 2 pending docs claimed; a second claim gets nothing.
set role service_role;
create temp table c1 as select id from public.claim_document_jobs(10, 600, 3);
create temp table c2 as select id from public.claim_document_jobs(10, 600, 3);
reset role;
do $$ begin
  assert (select count(*) from c1) = 2, 'first claim should take the 2 pending docs';
  assert (select count(*) from c2) = 0, 'second claim must not re-take claimed docs';
  raise notice 'PASS claim pending jobs';
end $$;

-- 2. Stale lease: pending A was held by a dead worker; the lease has expired, so it is reclaimed with attempts 2.
update public.documents set processing_started_at = now() - interval '1 hour'
 where id = 'a1000000-0000-4000-8000-000000000001';
set role service_role;
create temp table c3 as select id, processing_attempts from public.claim_document_jobs(10, 600, 3);
reset role;
do $$ begin
  assert (select count(*) from c3) = 1, 'stale job should be reclaimed exactly once';
  assert (select processing_attempts from c3) = 2, 'reclaim must increment attempts';
  raise notice 'PASS stale lease reclaimed';
end $$;

-- 3. Exhausted attempts: stale and at max attempts -> failed, not retried forever.
update public.documents set processing_started_at = now() - interval '1 hour', processing_attempts = 3
 where id = 'a1000000-0000-4000-8000-000000000002';
set role service_role;
create temp table c4 as select id from public.claim_document_jobs(10, 600, 3);
reset role;
do $$ begin
  assert (select count(*) from c4) = 0, 'exhausted job must not be claimed';
  assert (select processing_status from public.documents where id = 'a1000000-0000-4000-8000-000000000002') = 'failed', 'exhausted job must be failed';
  assert (select last_error from public.documents where id = 'a1000000-0000-4000-8000-000000000002') like '%maximum%', 'failure reason must be recorded';
  raise notice 'PASS exhausted job marked failed';
end $$;

-- 4. Publishing: a pending doc cannot publish; a ready replacement publishes and archives the old version in one step.
set role service_role;
do $$ begin
  begin
    perform public.publish_document_version('a1000000-0000-4000-8000-000000000001');
    raise exception 'publishing a non-ready document should fail';
  exception when sqlstate 'P0001' then null;
  end;
end $$;
select id, publication_status from public.publish_document_version('a1000000-0000-4000-8000-000000000004');
reset role;
do $$ begin
  assert (select publication_status from public.documents where id = 'a1000000-0000-4000-8000-000000000004') = 'published', 'replacement must be published';
  assert (select publication_status from public.documents where id = 'a1000000-0000-4000-8000-000000000003') = 'archived', 'old version must be archived in the same step';
  raise notice 'PASS atomic replacement publish';
end $$;

-- 5. Staff dashboards are scoped by RLS (security invoker).
select set_config('app.user_id', '10000000-0000-4000-8000-000000000001', false);
set role authenticated;
do $$ declare s jsonb := public.staff_dashboard_stats(); begin
  assert (s->>'open_tickets')::int = 1, 'faculty f1 sees 1 open ticket';
  assert (s->>'resolved_tickets')::int = 1, 'faculty f1 sees 1 resolved ticket';
  assert (s->>'unassigned_queue')::int = 1, 'faculty f1 queue has 1 unassigned ticket';
  assert (s->>'assigned_to_me')::int = 0, 'f1 has no open assigned ticket';
  raise notice 'PASS faculty dashboard scope';
end $$;
reset role;

select set_config('app.user_id', '10000000-0000-4000-8000-000000000003', false);
set role authenticated;
do $$ declare s jsonb := public.staff_dashboard_stats(); begin
  assert (s->>'open_tickets')::int = 1 and (s->>'resolved_tickets')::int = 0, 'authority c2 sees only the campus-2 ticket';
  raise notice 'PASS authority c2 scope';
end $$;
reset role;

select set_config('app.user_id', '10000000-0000-4000-8000-000000000002', false);
set role authenticated;
do $$ declare s jsonb := public.staff_dashboard_stats(); begin
  assert (s->>'open_tickets')::int = 1 and (s->>'resolved_tickets')::int = 1 and (s->>'unassigned_queue')::int = 1, 'authority c1 sees campus-1 tickets only';
  raise notice 'PASS authority c1 scope';
end $$;
reset role;

-- 6. Management aggregates are computed in SQL across campuses (service_role).
set role service_role;
do $$ declare m jsonb := public.management_ticket_stats(); begin
  assert (m->>'total_tickets')::int = 3, 'management sees all 3 tickets';
  assert (m->>'resolved_tickets')::int = 1, 'one resolved';
  assert (m->>'avg_first_response_hours')::numeric = 5.00, 'avg first response is 5 hours';
  assert jsonb_array_length(m->'campuses') = 2, 'two campuses';
  assert jsonb_array_length(m->'departments') = 2, 'two departments';
  raise notice 'PASS management aggregates';
end $$;
reset role;

-- 7. Privileges: only the intended roles can execute each function.
do $$ begin
  begin
    set local role authenticated;
    perform public.claim_document_jobs(1, 600, 3);
    raise exception 'authenticated must not claim jobs';
  exception when insufficient_privilege then null;
  end;
  reset role;
  begin
    set local role anon;
    perform public.staff_dashboard_stats();
    raise exception 'anon must not read staff stats';
  exception when insufficient_privilege then null;
  end;
  reset role;
  begin
    set local role authenticated;
    perform public.management_ticket_stats();
    raise exception 'authenticated must not read management stats';
  exception when insufficient_privilege then null;
  end;
  reset role;
  raise notice 'PASS function privileges';
end $$;
