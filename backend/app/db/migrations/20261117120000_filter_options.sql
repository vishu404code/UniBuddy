-- Filter options that Authority manages for each campus: academic years, batch years and sections.
--
-- Additive and backward-compatible. Existing documents, announcements and profiles keep their
-- values, even when a value is not in this list. Only new selections are checked against the
-- active options. Authority adds, activates, deactivates and removes options. Faculty and
-- students may read the active options of their own campus. Writes happen only through the
-- backend (secret key).
--
-- Removing an option that is already used is refused by the backend; it is deactivated instead.
-- Audiences and scopes are not stored here: they are fixed by the access rules.

create table public.filter_options (
  id uuid primary key default gen_random_uuid(),
  campus_id uuid not null references public.campuses(id) on delete cascade,
  kind text not null check (kind in ('academic_year', 'batch', 'section')),
  value text not null check (char_length(btrim(value)) between 1 and 20),
  active boolean not null default true,
  created_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint filter_options_batch_is_a_year check (kind <> 'batch' or value ~ '^[0-9]{4}$'),
  constraint filter_options_id_campus_key unique (id, campus_id)
);

-- Case-insensitive: "2026-27" and " 2026-27 " are the same option on a campus.
create unique index filter_options_campus_kind_value_key
  on public.filter_options (campus_id, kind, lower(btrim(value)));

create trigger filter_options_set_updated_at
  before update on public.filter_options
  for each row execute function public.set_updated_at();

alter table public.filter_options enable row level security;

create policy "filter_options_select_own_campus" on public.filter_options
  for select to authenticated
  using (campus_id = public.app_campus_id());

grant select on public.filter_options to authenticated;
