-- GENERATED from supabase/migrations/20261108120700_backend_operations.sql by tools/port_supabase_migrations.py. Do not edit by hand.
-- Backend operations: write and read-back grants for the secret-key backend,
-- one duplicate-ticket guard, and the retrieval function used by /chat/ask.
-- Each grant covers an endpoint that exists in app/. Nothing is granted to anon.

grant select, insert, update on public.documents to service_role;
grant insert on public.document_chunks to service_role;
grant select, insert on public.conversations to service_role;
grant select, insert on public.messages to service_role;
grant select, insert, update on public.tickets to service_role;
grant select, insert on public.ticket_events to service_role;
grant select, insert, update on public.notifications to service_role;
grant select, insert on public.announcements to service_role;
grant select on public.campuses to service_role;
grant select on public.departments to service_role;
grant usage, select on sequence public.ticket_number_seq to service_role;

-- One ticket per forwarded question, even when two requests race.
create unique index tickets_source_message_unique
  on public.tickets (source_message_id)
  where source_message_id is not null;

-- Similarity search that runs as the caller (security invoker), so RLS on
-- document_chunks and documents decides which chunks can be returned.
create or replace function public.match_document_chunks(
  query_embedding vector(1536),
  match_count int,
  min_similarity float
)
returns table (
  chunk_id uuid,
  document_id uuid,
  title text,
  page_number int,
  content text,
  similarity float
)
language sql
stable
security invoker
set search_path = public
as $$
  select
    dc.id,
    d.id,
    d.title,
    dc.page_number,
    dc.content,
    1 - (dc.embedding <=> query_embedding) as similarity
  from public.document_chunks dc
  join public.documents d on d.id = dc.document_id
  where dc.embedding is not null
    and 1 - (dc.embedding <=> query_embedding) >= min_similarity
  order by dc.embedding <=> query_embedding
  limit least(match_count, 20);
$$;

revoke execute on function public.match_document_chunks(vector, int, float) from public, anon;
grant execute on function public.match_document_chunks(vector, int, float) to authenticated;
