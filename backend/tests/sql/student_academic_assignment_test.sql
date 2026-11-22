-- Authority-only academic assignment (migration 20261122140000). Synthetic rows; rolled back at the end.
begin;
do $$
declare
  campus uuid := gen_random_uuid();
  other_campus uuid := gen_random_uuid();
  dept uuid := gen_random_uuid();
  authority uuid := gen_random_uuid();
  faculty uuid := gen_random_uuid();
  student uuid := gen_random_uuid();
  stranger uuid := gen_random_uuid();
  course uuid := gen_random_uuid();
  foreign_course uuid := gen_random_uuid();
  audit_before integer;
  batch_now integer;
begin
  insert into public.campuses (id, name, code) values
    (campus, 'Assign ' || campus::text, 'asg-' || left(campus::text, 8)),
    (other_campus, 'Other ' || other_campus::text, 'oth-' || left(other_campus::text, 8));
  insert into public.departments (id, campus_id, name) values (dept, campus, 'Dept');
  insert into public.account_identities (id, email, google_subject) values
    (authority, 'a-' || authority::text || '@example.test', 'sa-' || authority::text),
    (faculty, 'f-' || faculty::text || '@example.test', 'sf-' || faculty::text),
    (student, 's-' || student::text || '@example.test', 'ss-' || student::text),
    (stranger, 'x-' || stranger::text || '@example.test', 'sx-' || stranger::text);
  insert into public.profiles (id, email, role, campus_id, department_id) values
    (authority, 'a-' || authority::text || '@example.test', 'authority', campus, dept),
    (faculty, 'f-' || faculty::text || '@example.test', 'faculty', campus, dept),
    (student, 's-' || student::text || '@example.test', 'student', campus, dept),
    (stranger, 'x-' || stranger::text || '@example.test', 'student', other_campus, null);
  insert into public.filter_options (campus_id, kind, value, active) values
    (campus, 'batch', '2026', true), (campus, 'batch', '2025', false), (campus, 'section', 'A', true);
  insert into public.courses (id, campus_id, name, active) values (course, campus, 'Assign CS', true);
  insert into public.courses (id, campus_id, name, active) values (foreign_course, other_campus, 'Other CS', true);

  -- 1. Authority assigns active values: the profile changes and one audit row is written.
  select count(*) into audit_before from public.student_academic_audit where student_id = student;
  perform public.assign_student_academics(student, authority, 2026, 'A', course);
  select batch_year into batch_now from public.profiles where id = student;
  assert batch_now = 2026, 'the batch must be assigned';
  assert (select count(*) from public.student_academic_audit where student_id = student) = audit_before + 1,
    'the change must be audited';

  -- 2. Refusals: faculty actor, inactive batch, course from another campus, a student who is not a student.
  begin perform public.assign_student_academics(student, faculty, 2026, null, null); raise exception 'faculty accepted';
  exception when raise_exception then assert sqlerrm = 'not_authorized', 'faculty must be refused: ' || sqlerrm; end;
  begin perform public.assign_student_academics(student, authority, 2025, null, null); raise exception 'inactive batch accepted';
  exception when raise_exception then assert sqlerrm = 'batch_not_active', 'inactive batch must be refused: ' || sqlerrm; end;
  begin perform public.assign_student_academics(student, authority, null, null, foreign_course); raise exception 'foreign course accepted';
  exception when raise_exception then assert sqlerrm = 'course_not_active', 'foreign course must be refused: ' || sqlerrm; end;
  begin perform public.assign_student_academics(faculty, authority, 2026, null, null); raise exception 'non-student accepted';
  exception when raise_exception then assert sqlerrm = 'student_not_found', 'non-students must be refused: ' || sqlerrm; end;
  begin perform public.assign_student_academics(stranger, authority, 2026, null, null); raise exception 'other campus accepted';
  exception when raise_exception then assert sqlerrm = 'not_authorized', 'other-campus student must be refused: ' || sqlerrm; end;
  select batch_year into batch_now from public.profiles where id = student;
  assert batch_now = 2026, 'refused calls must not change the profile';

  -- 3. Null clears a field, and the change is audited.
  perform public.assign_student_academics(student, authority, null, null, null);
  select batch_year into batch_now from public.profiles where id = student;
  assert batch_now is null, 'null must clear the batch';
  raise notice 'PASS Authority-only assignment, active values only, audited';
end $$;
rollback;
