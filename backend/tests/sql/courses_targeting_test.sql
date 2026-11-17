\set ON_ERROR_STOP on
-- Courses and targeted announcements (migration 20261117100000).
-- Run inside one transaction that is rolled back, against a fixture database only. The fixtures
-- use fixed "70000000-" ids and "T-" titles, so no existing record is read or changed.

insert into public.account_identities (id) values
 ('70000000-0000-4000-8000-000000000001'),  -- faculty, campus 1
 ('70000000-0000-4000-8000-000000000002'),  -- authority, campus 1
 ('70000000-0000-4000-8000-000000000003'),  -- student S1, campus 1, batch 2026, BBA, A
 ('70000000-0000-4000-8000-000000000004'),  -- student S2, campus 1, batch 2025, CS, B
 ('70000000-0000-4000-8000-000000000005'),  -- student S3, campus 1, no academic fields
 ('70000000-0000-4000-8000-000000000006');  -- student S4, campus 2, batch 2026, its own BBA, A

insert into public.campuses (id, name, code) values
 ('71000000-0000-4000-8000-000000000001', 'Test Campus 1', 'tc1'),
 ('71000000-0000-4000-8000-000000000002', 'Test Campus 2', 'tc2');

insert into public.courses (id, campus_id, name) values
 ('72000000-0000-4000-8000-000000000001', '71000000-0000-4000-8000-000000000001', 'BBA'),
 ('72000000-0000-4000-8000-000000000002', '71000000-0000-4000-8000-000000000001', 'CS'),
 ('72000000-0000-4000-8000-000000000003', '71000000-0000-4000-8000-000000000002', 'BBA');

insert into public.profiles (id, email, role, campus_id, academic_year, batch_year, course_id, section) values
 ('70000000-0000-4000-8000-000000000001', 'fac@t.test', 'faculty', '71000000-0000-4000-8000-000000000001', null, null, null, null),
 ('70000000-0000-4000-8000-000000000002', 'auth@t.test', 'authority', '71000000-0000-4000-8000-000000000001', null, null, null, null),
 ('70000000-0000-4000-8000-000000000003', 's1@t.test', 'student', '71000000-0000-4000-8000-000000000001', '2026-27', 2026, '72000000-0000-4000-8000-000000000001', 'A'),
 ('70000000-0000-4000-8000-000000000004', 's2@t.test', 'student', '71000000-0000-4000-8000-000000000001', '2025-26', 2025, '72000000-0000-4000-8000-000000000002', 'B'),
 ('70000000-0000-4000-8000-000000000005', 's3@t.test', 'student', '71000000-0000-4000-8000-000000000001', null, null, null, null),
 ('70000000-0000-4000-8000-000000000006', 's4@t.test', 'student', '71000000-0000-4000-8000-000000000002', '2026-27', 2026, '72000000-0000-4000-8000-000000000003', 'A');

-- Announcements. Inserted as the owner, which bypasses RLS, so the visibility rules are tested below.
insert into public.announcements (id, audience, scope, campus_id, title, body, published_by, academic_year, batch_year, course_id, section) values
 ('73000000-0000-4000-8000-000000000001', 'all_students', 'campus', '71000000-0000-4000-8000-000000000001', 'T-ALL', 'everyone', '70000000-0000-4000-8000-000000000002', null, null, null, null),
 ('73000000-0000-4000-8000-000000000002', 'all_students', 'campus', '71000000-0000-4000-8000-000000000001', 'T-BATCH26', 'batch 2026', '70000000-0000-4000-8000-000000000002', null, 2026, null, null),
 ('73000000-0000-4000-8000-000000000003', 'all_students', 'campus', '71000000-0000-4000-8000-000000000001', 'T-BBA-A', 'BBA section A', '70000000-0000-4000-8000-000000000002', null, null, '72000000-0000-4000-8000-000000000001', 'A'),
 ('73000000-0000-4000-8000-000000000004', 'all_students', 'campus', '71000000-0000-4000-8000-000000000001', 'T-PERSON-S2', 'selected person', '70000000-0000-4000-8000-000000000002', null, null, null, null),
 ('73000000-0000-4000-8000-000000000005', 'all_students', 'campus', '71000000-0000-4000-8000-000000000001', 'T-S3-PLUS-B25', 'selected plus batch 2025', '70000000-0000-4000-8000-000000000002', null, 2025, null, null),
 ('73000000-0000-4000-8000-000000000006', 'staff_only', 'campus', '71000000-0000-4000-8000-000000000001', 'T-STAFF', 'staff only', '70000000-0000-4000-8000-000000000002', null, null, null, null),
 ('73000000-0000-4000-8000-000000000007', 'all_students', 'university_wide', '71000000-0000-4000-8000-000000000001', 'T-UNIWIDE-B26', 'university batch 2026', '70000000-0000-4000-8000-000000000002', null, 2026, null, null);

insert into public.announcement_recipients (announcement_id, profile_id) values
 ('73000000-0000-4000-8000-000000000004', '70000000-0000-4000-8000-000000000004'),
 ('73000000-0000-4000-8000-000000000005', '70000000-0000-4000-8000-000000000005');

-- Returns the titles of the T- fixtures that a user can read. It applies the same rules as the
-- announcements_select policy: all_students rows through announcement_visible_to_me(), and staff
-- rows for faculty and authority on their campus or university-wide. The owner role cannot switch
-- to the authenticated role on this database, so the policy text is checked separately below.
create or replace function pg_temp.titles_visible_to(uid uuid) returns text[]
language plpgsql as $$
declare out text[];
begin
  perform set_config('app.user_id', uid::text, true);
  select coalesce(array_agg(a.title order by a.title), '{}') into out
    from public.announcements a
   where a.title like 'T-%'
     and (
       (a.audience = 'all_students' and public.announcement_visible_to_me(a))
       or exists (
         select 1 from public.profiles p
          where p.id = uid and p.role in ('faculty', 'authority')
            and (a.scope = 'university_wide' or a.campus_id = p.campus_id)
       )
     );
  return out;
end $$;

-- The policy must use the shared visibility function, and students must have no direct grant on recipients.
do $$ begin
  assert (select qual from pg_policies where tablename = 'announcements' and policyname = 'announcements_select')
           like '%announcement_visible_to_me%', 'announcements_select uses announcement_visible_to_me';
  assert not has_table_privilege('authenticated', 'public.announcement_recipients', 'select'),
    'authenticated users have no direct select on announcement_recipients';
  assert not has_table_privilege('anon', 'public.announcement_recipients', 'select'),
    'anon has no direct select on announcement_recipients';
  raise notice 'PASS policy wiring and recipient privileges';
end $$;

do $$ begin
  assert pg_temp.titles_visible_to('70000000-0000-4000-8000-000000000003') = array['T-ALL','T-BATCH26','T-BBA-A','T-UNIWIDE-B26'],
    'S1 (batch 2026, BBA, section A, campus 1) sees the untargeted, batch and course matches only';
  raise notice 'PASS student S1 sees matching announcements only';
end $$;

do $$ begin
  assert pg_temp.titles_visible_to('70000000-0000-4000-8000-000000000004') = array['T-ALL','T-PERSON-S2','T-S3-PLUS-B25'],
    'S2 sees the selected-person announcement and the batch 2025 match, not the batch 2026 ones';
  raise notice 'PASS student S2 sees selected-person and batch matches';
end $$;

do $$ begin
  assert pg_temp.titles_visible_to('70000000-0000-4000-8000-000000000005') = array['T-ALL','T-S3-PLUS-B25'],
    'S3 with no academic fields sees only untargeted announcements and those that select S3';
  raise notice 'PASS student with no academic fields is not matched by filters';
end $$;

do $$ begin
  assert pg_temp.titles_visible_to('70000000-0000-4000-8000-000000000006') = array['T-ALL','T-UNIWIDE-B26'],
    'a student on campus 2 does not see a campus 1 batch announcement, but sees a university-wide one';
  raise notice 'PASS campus-scoped targeting does not cross campuses';
end $$;

do $$ begin
  assert pg_temp.titles_visible_to('70000000-0000-4000-8000-000000000001') = array['T-ALL','T-BATCH26','T-BBA-A','T-PERSON-S2','T-S3-PLUS-B25','T-STAFF','T-UNIWIDE-B26'],
    'faculty on campus 1 still see every announcement of their campus';
  raise notice 'PASS faculty visibility is unchanged';
end $$;

do $$ begin
  assert pg_temp.titles_visible_to('70000000-0000-4000-8000-000000000002') = array['T-ALL','T-BATCH26','T-BBA-A','T-PERSON-S2','T-S3-PLUS-B25','T-STAFF','T-UNIWIDE-B26'],
    'authority on campus 1 still see every announcement of their campus';
  raise notice 'PASS authority visibility is unchanged';
end $$;

-- Profile course must belong to the same campus.
do $$ declare caught text; begin
  caught := null;
  begin
    update public.profiles set course_id = '72000000-0000-4000-8000-000000000003'
    where id = '70000000-0000-4000-8000-000000000003';
  exception when foreign_key_violation then caught := 'refused';
  end;
  assert caught = 'refused', 'a campus 1 student cannot be given a campus 2 course';
  raise notice 'PASS course must belong to the same campus';
end $$;

-- A referenced course cannot be hard-deleted; the backend then deactivates it instead.
do $$ declare caught text; begin
  caught := null;
  begin
    delete from public.courses where id = '72000000-0000-4000-8000-000000000001';
  exception when foreign_key_violation then caught := 'refused';
  end;
  assert caught = 'refused', 'a course in use cannot be deleted';
  raise notice 'PASS a course in use is protected from hard delete';
end $$;
