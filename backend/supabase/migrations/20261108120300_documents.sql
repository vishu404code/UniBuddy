-- Milestone 2: documents and their chunks/embeddings.
--
-- IMPORTANT access-control note (see Milestone 2 report): `campus_id` and
-- `department_id` on a document are for ATTRIBUTION and ROUTING only. Per
-- the confirmed project rule, retrieval must NOT be silently filtered by a
-- student's campus. The only thing that restricts whether a student can see
-- a document is `visibility` (plus `publication_status` actually being
-- 'published'). These RLS policies enforce that -- but the backend's own
-- retrieval query (Milestone 3, run with the service_role key) bypasses RLS
-- entirely and MUST apply the same publication_status/visibility filter
-- explicitly in its SQL. RLS here is a safety net, not the only gate.

create table public.documents (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  original_filename text,
  mime_type text,
  file_size_bytes bigint,
  storage_path text not null,
  uploaded_by uuid not null references public.profiles(id),
  campus_id uuid references public.campuses(id),
  department_id uuid references public.departments(id),
  visibility text not null default 'public_students'
    check (visibility in ('public_students', 'staff_only')),
  processing_status text not null default 'pending'
    check (processing_status in ('pending', 'processing', 'ready', 'failed')),
  publication_status text not null default 'draft'
    check (publication_status in ('draft', 'published', 'archived')),
  page_count integer,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
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

-- Vector similarity index (cosine distance, matching how OpenAI embeddings
-- are typically compared). Created now, empty, so it's ready for Milestone 3.
create index document_chunks_embedding_idx
  on public.document_chunks
  using hnsw (embedding vector_cosine_ops);

alter table public.documents enable row level security;
alter table public.document_chunks enable row level security;

-- Readable by: its uploader, any staff role, or any authenticated student
-- IF it's published AND marked public_students. Never filtered by campus.
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
