-- Announcements and notifications.
--
-- Announcement visibility is explicit, like documents. `audience` decides who
-- can read an announcement. `campus_id` and `department_id` are attribution and
-- routing only and never restrict who can see an announcement.
-- Writes happen only through the backend (service_role).

create table public.announcements (
  id uuid primary key default gen_random_uuid(),
  audience text not null default 'all_students'
    check (audience in ('all_students', 'staff_only')),
  campus_id uuid references public.campuses(id),
  department_id uuid,
  category text,
  title text not null,
  body text not null,
  is_important boolean not null default false,
  published_by uuid not null references public.profiles(id),
  created_at timestamptz not null default now(),
  constraint announcements_department_in_campus
    foreign key (department_id, campus_id)
    references public.departments(id, campus_id),
  constraint announcements_department_requires_campus
    check (department_id is null or campus_id is not null)
);

create index announcements_campus_id_idx on public.announcements(campus_id);
create index announcements_audience_idx on public.announcements(audience);

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

create policy "announcements_select" on public.announcements
  for select to authenticated
  using (
    audience = 'all_students'
    or public.app_role() in ('faculty', 'authority', 'management')
  );

create policy "notifications_select_own" on public.notifications
  for select to authenticated
  using (user_id = auth.uid());

grant select on public.announcements to authenticated;
grant select on public.notifications to authenticated;
