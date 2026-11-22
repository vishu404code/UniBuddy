-- Document targeting, enforced on the server.
--
-- A document may carry academic targeting (academic_year, batch_year, section, course_id). Before this
-- migration only the browser filtered on it, so any signed-in student on the campus could list, open
-- (PDF route), search (chat retrieval) or read the chunks of a document meant for another batch.
--
-- Rule, the same one announcements already use (20261117100000):
--   - a document with no targeting fields is visible exactly as before;
--   - for a student, each targeting field that is set must equal the student's profile value;
--   - staff (faculty, authority) and the uploader are unchanged.
--
-- Every read path goes through can_read_document(): the documents policy, the chunk policy used by
-- match_document_chunks, and the list, detail and file routes. Changing that one rule covers them all.
--
-- Additive: no column or policy is removed. The helper only reads the caller's own profile row and
-- takes the caller from unibuddy_auth.user_id(), so it cannot reveal another person's profile.

create or replace function public.student_matches_document_targeting(doc public.documents)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
      from public.profiles p
     where p.id = unibuddy_auth.user_id()
       and (doc.academic_year is null or doc.academic_year = p.academic_year)
       and (doc.batch_year is null or doc.batch_year = p.batch_year)
       and (doc.section is null or doc.section = p.section)
       and (doc.course_id is null or doc.course_id = p.course_id)
  );
$$;

revoke execute on function public.student_matches_document_targeting(public.documents) from public, anon;
grant execute on function public.student_matches_document_targeting(public.documents) to authenticated, service_role;

create or replace function public.can_read_document(doc public.documents)
returns boolean
language sql
stable
set search_path = public
as $$
  select
    doc.uploaded_by = unibuddy_auth.user_id()
    or (
      doc.publication_status = 'published'
      and doc.visibility = 'public_students'
      and (doc.scope = 'university_wide' or doc.campus_id = public.app_campus_id())
      -- Students only see a targeted document when their profile matches it. Staff are not filtered.
      and (public.app_role() is distinct from 'student' or public.student_matches_document_targeting(doc))
    )
    or (
      doc.publication_status = 'published'
      and doc.visibility = 'staff_only'
      and public.app_role() in ('faculty', 'authority')
      and (doc.scope = 'university_wide' or doc.campus_id = public.app_campus_id())
    )
    or (
      doc.publication_status in ('draft', 'archived')
      and public.app_role() = 'authority'
      and (doc.scope = 'university_wide' or doc.campus_id = public.app_campus_id())
    );
$$;

revoke execute on function public.can_read_document(public.documents) from public, anon;
grant execute on function public.can_read_document(public.documents) to authenticated, service_role;
