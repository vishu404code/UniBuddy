-- Milestone 2: announcements and notifications.

create table public.announcements (
  id uuid primary key default gen_random_uuid(),
  campus_id uuid references public.campuses(id),  -- null = university-wide
  department_id uuid references public.departments(id),
  category text,
  title text not null,
  body text not null,
  is_important boolean not null default false,
  published_by uuid not null references public.profiles(id),
  created_at timestamptz not null default now()
);

create index announcements_campus_id_idx on public.announcements(campus_id);

create table public.notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  text text not null,
  ticket_id uuid references public.tickets(id),
  is_read boolean not null default false,
  created_at timestamptz not null default now()
);

create index notifications_user_id_idx on public.notifications(user_id);

alter table public.announcements enable row level security;
alter table public.notifications enable row level security;

-- Readable by every authenticated user for now, regardless of campus_id.
-- Whether campus-specific announcements should actually be hidden from
-- other campuses' students is an open question -- see Milestone 2 report.
create policy "announcements_select_authenticated" on public.announcements
  for select to authenticated using (true);

create policy "notifications_select_own" on public.notifications
  for select to authenticated
  using (user_id = auth.uid());

grant select on public.announcements to authenticated;
grant select on public.notifications to authenticated;
