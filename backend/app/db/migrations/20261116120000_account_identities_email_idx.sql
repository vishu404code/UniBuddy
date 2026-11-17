-- Index on account_identities(email) for fast lookup during Google sign-in/sign-up.
create index if not exists account_identities_email_idx on public.account_identities (lower(email));
create index if not exists account_identities_raw_email_idx on public.account_identities (email);
