-- Knowledge Management: Text Content, Document Metadata & Management Role Access
-- Migration: 20261109150000_knowledge_management.sql

alter table public.documents
  add column if not exists item_type text not null default 'file'
    check (item_type in ('file', 'text_content')),
  add column if not exists category text default 'General',
  add column if not exists description text,
  add column if not exists raw_content text,
  add column if not exists effective_date date,
  add column if not exists expiry_date date,
  add column if not exists tags text[] default '{}'::text[];

-- Make storage_path optional for text-based content items
alter table public.documents alter column storage_path drop not null;

-- Update can_read_document to grant Management access to staff & draft content
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
    )
    or (
      doc.publication_status = 'published'
      and doc.visibility = 'staff_only'
      and public.app_role() in ('faculty', 'authority', 'management')
      and (doc.scope = 'university_wide' or doc.campus_id = public.app_campus_id())
    )
    or (
      doc.publication_status in ('draft', 'archived')
      and public.app_role() in ('authority', 'management')
      and (doc.scope = 'university_wide' or doc.campus_id = public.app_campus_id())
    );
$$;
