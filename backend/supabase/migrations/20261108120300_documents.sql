-- Documents and their chunks/embeddings.
--
-- Access rule: `campus_id` and `department_id` are for attribution, routing and
-- reporting only. Retrieval is never filtered by a student's campus. What
-- restricts a document is `visibility` plus `publication_status`.
--
-- The backend's retrieval query runs with the service_role key, which bypasses
-- RLS. It must apply the same publication_status and visibility filter in its
-- own SQL. These policies are a second line of defence, not the only gate.

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
    check (department_id is null or campus_id is not null)
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

alter table public.documents enable row level security;
alter table public.document_chunks enable row level security;

-- Readable by the uploader, any staff role, or any authenticated user when the
-- document is published and marked public_students. Never filtered by campus.
create policy "documents_select" on public.documents
  for select to authenticated
  using (
    uploaded_by = auth.uid()
    or public.app_role() in ('faculty', 'authority', 'management')
    or (publication_status = 'published' and visibility = 'public_students')
  );

create policy "document_chunks_select" on public.document_chunks
  for select to authenticated
  using (
    exists (
      select 1 from public.documents d
      where d.id = document_chunks.document_id
        and (
          d.uploaded_by = auth.uid()
          or public.app_role() in ('faculty', 'authority', 'management')
          or (d.publication_status = 'published' and d.visibility = 'public_students')
        )
    )
  );

grant select on public.documents to authenticated;
grant select on public.document_chunks to authenticated;
