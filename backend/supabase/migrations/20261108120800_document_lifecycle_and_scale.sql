-- Document lifecycle, resilient processing, and database-side aggregates.
-- Unapplied until explicitly approved. Tested on a local PostgreSQL 17 + pgvector
-- database before being proposed for the dev project.

-- Processing state that survives worker restarts.
alter table public.documents
  add column processing_started_at timestamptz,
  add column processing_attempts integer not null default 0,
  add column last_error text,
  add column replaces_document_id uuid references public.documents(id),
  add constraint documents_not_self_replacing check (replaces_document_id is null or replaces_document_id <> id);

create index documents_claim_idx on public.documents (processing_status, created_at);
create index documents_replaces_idx on public.documents (replaces_document_id);
create index documents_created_at_idx on public.documents (created_at desc);

-- Keyset-friendly ordering and filters for list endpoints.
create index tickets_created_at_idx on public.tickets (created_at desc);
create index tickets_status_created_idx on public.tickets (status, created_at desc);
create index tickets_department_created_idx on public.tickets (department_id, created_at desc);
create index ticket_events_reply_idx on public.ticket_events (ticket_id, created_at) where event_type = 'reply';
create index announcements_created_at_idx on public.announcements (created_at desc);
create index notifications_user_created_idx on public.notifications (user_id, created_at desc);
create index messages_conversation_created_idx on public.messages (conversation_id, created_at);

-- Re-processing deletes a document's old chunks before inserting new ones.
grant select, delete on public.document_chunks to service_role;

-- Claims pending documents, plus documents whose worker stopped without finishing
-- (lease expired). Claiming uses SKIP LOCKED, so parallel workers never take the same job.
-- Documents that have used all attempts are marked failed instead of retried forever.
create or replace function public.claim_document_jobs(
  p_limit integer,
  p_lease_seconds integer,
  p_max_attempts integer
)
returns setof public.documents
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.documents
     set processing_status = 'failed',
         last_error = 'Processing did not finish after the maximum number of attempts'
   where processing_status = 'processing'
     and processing_started_at < now() - make_interval(secs => p_lease_seconds)
     and processing_attempts >= p_max_attempts;

  return query
  with candidates as (
    select id
      from public.documents
     where (processing_status = 'pending' and processing_attempts < p_max_attempts)
        or (processing_status = 'processing'
            and processing_started_at < now() - make_interval(secs => p_lease_seconds)
            and processing_attempts < p_max_attempts)
     order by created_at
     limit p_limit
     for update skip locked
  )
  update public.documents d
     set processing_status = 'processing',
         processing_started_at = now(),
         processing_attempts = d.processing_attempts + 1
    from candidates c
   where d.id = c.id
  returning d.*;
end;
$$;

-- Publishes a ready draft. If it replaces another document, that document is
-- archived in the same transaction, so students never see both versions.
create or replace function public.publish_document_version(p_document_id uuid)
returns public.documents
language plpgsql
security definer
set search_path = public
as $$
declare
  published public.documents;
begin
  update public.documents
     set publication_status = 'published'
   where id = p_document_id
     and publication_status = 'draft'
     and processing_status = 'ready'
  returning * into published;

  if not found then
    raise exception 'document_not_publishable' using errcode = 'P0001';
  end if;

  if published.replaces_document_id is not null then
    update public.documents
       set publication_status = 'archived'
     where id = published.replaces_document_id
       and publication_status = 'published';
  end if;

  return published;
end;
$$;

-- Staff dashboard. Security invoker, so every count is limited to the rows the
-- caller can already see under RLS.
create or replace function public.staff_dashboard_stats()
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
  with visible_tickets as (
    select t.id, t.status, t.department_id, t.assigned_faculty_id, t.created_at
      from public.tickets t
  ),
  first_replies as (
    select e.ticket_id, min(e.created_at) as first_reply_at
      from public.ticket_events e
     where e.event_type = 'reply'
     group by e.ticket_id
  )
  select jsonb_build_object(
    'open_tickets', (select count(*) from visible_tickets where status <> 'resolved'),
    'resolved_tickets', (select count(*) from visible_tickets where status = 'resolved'),
    'tickets_by_status', (
      select coalesce(jsonb_object_agg(status, n), '{}'::jsonb)
        from (select status, count(*) as n from visible_tickets group by status) s
    ),
    'unassigned_queue', (
      select count(*) from visible_tickets where assigned_faculty_id is null and status = 'submitted'
    ),
    'assigned_to_me', (
      select count(*) from visible_tickets
       where assigned_faculty_id = auth.uid() and status <> 'resolved'
    ),
    'avg_first_response_hours', (
      select round(avg(extract(epoch from (r.first_reply_at - t.created_at)) / 3600.0)::numeric, 2)
        from visible_tickets t
        join first_replies r on r.ticket_id = t.id
    ),
    'by_department', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'department_id', d.id,
               'name', d.name,
               'total', x.total,
               'resolved', x.resolved
             ) order by d.name), '[]'::jsonb)
        from (
          select department_id,
                 count(*) as total,
                 count(*) filter (where status = 'resolved') as resolved
            from visible_tickets
           group by department_id
        ) x
        join public.departments d on d.id = x.department_id
    ),
    'drafts_visible', (select count(*) from public.documents where publication_status = 'draft'),
    'published_visible', (select count(*) from public.documents where publication_status = 'published')
  );
$$;

-- Management reporting. Aggregates only; computed in the database for every ticket.
-- Granted to service_role only. The route checks role = management before calling it.
create or replace function public.management_ticket_stats()
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
  with first_replies as (
    select e.ticket_id, min(e.created_at) as first_reply_at
      from public.ticket_events e
     where e.event_type = 'reply'
     group by e.ticket_id
  ),
  base as (
    select t.campus_id, t.department_id, t.status,
           extract(epoch from (r.first_reply_at - t.created_at)) / 3600.0 as response_hours
      from public.tickets t
      left join first_replies r on r.ticket_id = t.id
  ),
  by_campus as (
    select campus_id,
           count(*) as total,
           count(*) filter (where status = 'resolved') as resolved,
           avg(response_hours) as avg_hours
      from base group by campus_id
  ),
  by_department as (
    select department_id,
           count(*) as total,
           count(*) filter (where status = 'resolved') as resolved,
           avg(response_hours) as avg_hours
      from base group by department_id
  ),
  totals as (
    select count(*) as total,
           count(*) filter (where status = 'resolved') as resolved,
           avg(response_hours) as avg_hours
      from base
  )
  select jsonb_build_object(
    'total_tickets', (select total from totals),
    'resolved_tickets', (select resolved from totals),
    'resolution_rate', (select round(resolved::numeric / nullif(total, 0), 4) from totals),
    'avg_first_response_hours', (select round(avg_hours::numeric, 2) from totals),
    'campuses', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'id', b.campus_id, 'name', c.name,
               'total_tickets', b.total, 'resolved_tickets', b.resolved,
               'resolution_rate', round(b.resolved::numeric / nullif(b.total, 0), 4),
               'avg_first_response_hours', round(b.avg_hours::numeric, 2)
             ) order by c.name), '[]'::jsonb)
        from by_campus b join public.campuses c on c.id = b.campus_id
    ),
    'departments', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'id', d.id, 'name', d.name,
               'total_tickets', b.total, 'resolved_tickets', b.resolved,
               'resolution_rate', round(b.resolved::numeric / nullif(b.total, 0), 4),
               'avg_first_response_hours', round(b.avg_hours::numeric, 2)
             ) order by d.name), '[]'::jsonb)
        from by_department b join public.departments d on d.id = b.department_id
    ),
    'generated_at', now()
  );
$$;

-- Function privileges: only what each caller needs.
revoke execute on function public.claim_document_jobs(integer, integer, integer) from public, anon, authenticated;
revoke execute on function public.publish_document_version(uuid) from public, anon;
revoke execute on function public.staff_dashboard_stats() from public, anon;
revoke execute on function public.management_ticket_stats() from public, anon, authenticated;
grant execute on function public.claim_document_jobs(integer, integer, integer) to service_role;
grant execute on function public.publish_document_version(uuid) to service_role;
grant execute on function public.staff_dashboard_stats() to authenticated;
grant execute on function public.management_ticket_stats() to service_role;

-- Row-level security performance. Wrapping the helper calls in scalar subqueries lets
-- Postgres evaluate each once per statement instead of once per row. Only the form changes;
-- the rules are identical. Measured locally on 200k tickets: the authority dashboard went
-- from about 3.2 s to about 0.15 s per call.
alter policy tickets_select on public.tickets using (
  student_id = (select auth.uid())
  or assigned_faculty_id = (select auth.uid())
  or ((select public.app_role()) = 'faculty'
      and campus_id = (select public.app_campus_id())
      and department_id = (select public.app_department_id()))
  or ((select public.app_role()) = 'authority' and campus_id = (select public.app_campus_id()))
  or (select public.app_cross_campus_records())
);

alter policy ticket_events_select on public.ticket_events using (
  ticket_id in (select t.id from public.tickets t)
);

alter policy profiles_select on public.profiles using (
  id = (select auth.uid())
  or (select public.app_cross_campus_records())
  or ((select public.app_role()) in ('faculty', 'authority')
      and campus_id = (select public.app_campus_id()))
);

alter policy announcements_select on public.announcements using (
  audience = 'all_students'
  or ((select public.app_role()) in ('faculty', 'authority')
      and (scope = 'university_wide' or campus_id = (select public.app_campus_id())))
);
