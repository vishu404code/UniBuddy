-- Documents and their chunks/embeddings.
--
-- Access rules:
--   published + public_students  -> every authenticated user, across all campuses
--   published + staff_only       -> faculty and authority on the document's campus;
--                                   any campus only when scope = 'university_wide'.
--                                   Management has no access to staff content here.
--   draft or archived            -> the uploader, plus authority reviewers on the
--                                   document's campus (any campus if university_wide)
--
-- `campus_id` is required unless scope is 'university_wide', so every campus-scoped
-- document has a campus to check against. Retrieval never filters student-facing
-- documents by campus.
--
-- The backend's retrieval query runs with the secret key, which bypasses
-- RLS. It must apply the same rules in its own SQL. These policies are a second
-- line of defence.

create table public.documents (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  original_filename text,
  mime_type text,
  file_size_bytes bigint,
  storage_path text not null,
  uploaded_by uuid not null references public.profiles(id),
  campus_id uuid references public.campuses(id),
  department_id uuid,
  scope text not null default 'campus'
    check (scope in ('campus', 'university_wide')),
  visibility text not null default 'public_students'
    check (visibility in ('public_students', 'staff_only')),
  processing_status text not null default 'pending'
    check (processing_status in ('pending', 'processing', 'ready', 'failed')),
  publication_status text not null default 'draft'
    check (publication_status in ('draft', 'published', 'archived')),
  page_count integer,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint documents_department_in_campus
    foreign key (department_id, campus_id)
    references public.departments(id, campus_id),
  constraint documents_department_requires_campus
    check (department_id is null or campus_id is not null),
  constraint documents_campus_scope_requires_campus
    check (scope = 'university_wide' or campus_id is not null)
);

create index documents_uploaded_by_idx on public.documents(uploaded_by);
create index documents_campus_id_idx on public.documents(campus_id);
create index documents_department_id_idx on public.documents(department_id);
create index documents_status_idx
  on public.documents(processing_status, publication_status);

create trigger documents_set_updated_at
  before update on public.documents
  for each row execute function public.set_updated_at();

create table public.document_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.documents(id) on delete cascade,
  chunk_index integer not null,
  page_number integer,
  content text not null,
  embedding vector(1536),
  created_at timestamptz not null default now(),
  unique (document_id, chunk_index)
);

create index document_chunks_document_id_idx on public.document_chunks(document_id);

-- Cosine distance, matching how OpenAI embeddings are compared.
create index document_chunks_embedding_idx
  on public.document_chunks
  using hnsw (embedding vector_cosine_ops);

-- One definition of document access, shared by documents and document_chunks.
create or replace function public.can_read_document(doc public.documents)
returns boolean
language sql
stable
set search_path = public
as $$
  select
    doc.uploaded_by = auth.uid()
    or (
      doc.publication_status = 'published'
      and doc.visibility = 'public_students'
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

alter table public.documents enable row level security;
alter table public.document_chunks enable row level security;

create policy "documents_select" on public.documents
  for select to authenticated
  using (public.can_read_document(documents));

create policy "document_chunks_select" on public.document_chunks
  for select to authenticated
  using (
    exists (
      select 1 from public.documents d
      where d.id = document_chunks.document_id
        and public.can_read_document(d)
    )
  );

grant select on public.documents to authenticated;
grant select on public.document_chunks to authenticated;
