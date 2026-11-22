-- Ticket update in one transaction (migration 20261122130000). Synthetic rows; rolled back at the end.
begin;
do $$
declare
  campus uuid := gen_random_uuid();
  dept uuid := gen_random_uuid();
  student uuid := gen_random_uuid();
  faculty uuid := gen_random_uuid();
  ticket uuid := gen_random_uuid();
  status_now text;
  events_before integer;
begin
  insert into public.campuses (id, name, code) values (campus, 'Atomic ' || campus::text, 'atomic-' || left(campus::text, 8));
  insert into public.departments (id, campus_id, name) values (dept, campus, 'Dept');
  insert into public.account_identities (id, email, google_subject) values
    (student, 'student-' || student::text || '@example.test', 'sub-' || student::text),
    (faculty, 'faculty-' || faculty::text || '@example.test', 'sub-' || faculty::text);
  insert into public.profiles (id, email, role, campus_id, department_id) values
    (student, 'student-' || student::text || '@example.test', 'student', campus, dept),
    (faculty, 'faculty-' || faculty::text || '@example.test', 'faculty', campus, dept);
  insert into public.tickets (id, student_id, campus_id, department_id, subject, question, status)
    values (ticket, student, campus, dept, 'q', 'q', 'submitted');

  -- 1. A successful update writes the status, the event and the notification together.
  perform public.apply_ticket_update(
    ticket, 'submitted', 'assigned', faculty,
    jsonb_build_array(jsonb_build_object('event_type', 'assignment', 'note', 'Ticket taken', 'actor_id', faculty::text)),
    jsonb_build_array(jsonb_build_object('user_id', student::text, 'text', 'Ticket assigned')));
  select status into status_now from public.tickets where id = ticket;
  assert status_now = 'assigned', 'the status must change';
  assert (select count(*) from public.ticket_events where ticket_id = ticket) = 1, 'the event must be written';
  assert (select count(*) from public.notifications where ticket_id = ticket) = 1, 'the notification must be written';

  -- 2. A stale expected status is refused and writes nothing.
  begin
    perform public.apply_ticket_update(ticket, 'submitted', 'resolved', null, '[]'::jsonb, '[]'::jsonb);
    raise exception 'a stale update was accepted';
  exception when raise_exception then
    assert sqlerrm = 'ticket_changed', 'a stale update must raise ticket_changed, got: ' || sqlerrm;
  end;
  select status into status_now from public.tickets where id = ticket;
  assert status_now = 'assigned', 'a refused update must leave the status unchanged';

  -- 3. A failure after the status write rolls the whole call back: no status change, no event.
  select count(*) into events_before from public.ticket_events where ticket_id = ticket;
  begin
    perform public.apply_ticket_update(
      ticket, 'assigned', 'in_progress', null,
      jsonb_build_array(jsonb_build_object('event_type', 'status_change', 'note', 'In progress', 'actor_id', faculty::text)),
      jsonb_build_array(jsonb_build_object('user_id', gen_random_uuid()::text, 'text', 'to a missing user')));
    raise exception 'a notification to a missing user was accepted';
  exception when foreign_key_violation then
    null;
  end;
  select status into status_now from public.tickets where id = ticket;
  assert status_now = 'assigned', 'a failed update must leave the status unchanged';
  assert (select count(*) from public.ticket_events where ticket_id = ticket) = events_before,
    'a failed update must write no event';
  raise notice 'PASS ticket update is one transaction and refuses stale changes';
end $$;
rollback;
