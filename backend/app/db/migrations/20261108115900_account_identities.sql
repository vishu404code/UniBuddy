-- Account identities: one row per UniBuddy account. Google verifies the person; roles never live here.
--
-- One row per UniBuddy account. Google verifies the person, and google_subject is the
-- stable Google ID. Profiles reference this table, so profile IDs stay the same when
-- an existing account is linked to Google. Roles never live here.

create table public.account_identities (
  id uuid primary key default gen_random_uuid(),
  email text,
  google_subject text unique,
  created_at timestamptz not null default now()
);

alter table public.account_identities enable row level security;
-- No policies and no grants to anon or authenticated: only the backend reads and writes it.
grant select, insert, update on public.account_identities to service_role;
