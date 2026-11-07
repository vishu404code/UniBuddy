-- Milestone 2: tickets and their event timeline.
--
-- Note (see Milestone 2 report): `department_id` here is not currently
-- constrained to belong to the same `campus_id` as the ticket -- Postgres
-- CHECK constraints can't reference another table directly. The backend
-- must enforce "department belongs to this campus" when creating a ticket
-- (Milestone 4).

create sequence public.ticket_number_seq;

create table public.tickets (
  id uuid primary key default gen_random_uuid(),
  ticket_number text not null unique
    default ('UB-' || lpad(nextval('public.ticket_number_seq')::text, 4, '0')),
  student_id uuid not null references public.profiles(id),
  campus_id uuid not null references public.campuses(id),
  department_id uuid not null references public.departments(id),
  assigned_faculty_id uuid references public.profiles(id),
  subject text not null,
  question text not null,
  description text,
  priority text not null default 'medium'
    check (priority in ('low', 'medium', 'high')),
  status text not null default 'submitted'
    check (status in ('submitted', 'assigned', 'in_progress', 'resolved')),
  source_message_id uuid references public.messages(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index tickets_student_id_idx on public.tickets(student_id);
create index tickets_assigned_faculty_id_idx on public.tickets(assigned_faculty_id);
create index tickets_campus_department_idx on public.tickets(campus_id, department_id);
create index tickets_status_idx on public.tickets(status);

create trigger tickets_set_updated_at
  before update on public.tickets
  for each row execute function public.set_updated_at();

create table public.ticket_events (
  id uuid primary key default gen_random_uuid(),
  ticket_id uuid not null references public.tickets(id) on delete cascade,
  actor_id uuid references public.profiles(id),
  event_type text not null check (event_type in ('status_change', 'reply', 'assignment')),
  note text,
  created_at timestamptz not null default now()
);

create index ticket_events_ticket_id_idx on public.ticket_events(ticket_id);

alter table public.tickets enable row level security;
alter table public.ticket_events enable row level security;

-- Visible to: the student who filed it, the faculty member assigned to it,
-- and authority/management (oversight + cross-campus reporting).
create policy "tickets_select" on public.tickets
  for select to authenticated
  using (
    student_id = auth.uid()
    or assigned_faculty_id = auth.uid()
    or public.app_role() in ('authority', 'management')
  );

create policy "ticket_events_select" on public.ticket_events
  for select to authenticated
  using (
    exists (
      select 1 from public.tickets t
      where t.id = ticket_events.ticket_id
        and (
          t.student_id = auth.uid()
          or t.assigned_faculty_id = auth.uid()
          or public.app_role() in ('authority', 'management')
        )
    )
  );

grant select on public.tickets to authenticated;
grant select on public.ticket_events to authenticated;
