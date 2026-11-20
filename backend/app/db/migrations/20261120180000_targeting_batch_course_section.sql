-- Academic Targeting: Batch Year, Course, and Section for Documents & Announcements
-- Migration: 20261120180000_targeting_batch_course_section.sql

alter table public.documents
  add column if not exists batch_year integer,
  add column if not exists course text,
  add column if not exists course_id text,
  add column if not exists section text;

alter table public.announcements
  add column if not exists batch_year integer,
  add column if not exists course text,
  add column if not exists course_id text,
  add column if not exists section text;

create index if not exists documents_targeting_idx on public.documents (batch_year, course, section);
create index if not exists announcements_targeting_idx on public.announcements (batch_year, course, section);
