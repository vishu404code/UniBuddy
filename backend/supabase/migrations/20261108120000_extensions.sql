-- Milestone 2: core extensions and shared helpers.

create extension if not exists pgcrypto;  -- gen_random_uuid()
create extension if not exists vector;    -- pgvector, for document_chunks.embedding

-- Generic trigger function: keeps `updated_at` current on any table that has it.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;
