-- Student registration requests. A request grants nothing: it only queues a person for review.
-- Approval (which creates the account through the audited provisioning path) is not built yet,
-- because campus routing and the approver are open decisions.

create table public.registration_requests (
  id uuid primary key default gen_random_uuid(),
  email text not null check (email = lower(email) and email like '%@%'),
  full_name text not null check (char_length(full_name) between 2 and 120),
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
  requested_at timestamptz not null default now(),
  decided_at timestamptz,
  decided_by uuid references public.profiles(id),
  decision_reason text
);

-- One open request per address. Duplicate submissions are answered the same way as a first submission.
create unique index registration_requests_one_pending_per_email
  on public.registration_requests (email)
  where status = 'pending';

create index registration_requests_status_idx on public.registration_requests (status, requested_at);

-- Only the server can read or write this table. No API role may read or write it directly.
alter table public.registration_requests enable row level security;
revoke all on public.registration_requests from anon, authenticated;
grant select, insert, update on public.registration_requests to service_role;
