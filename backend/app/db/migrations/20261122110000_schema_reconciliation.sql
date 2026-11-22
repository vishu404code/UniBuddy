-- Schema reconciliation with the live database. PREPARED, NOT APPLIED.
--
-- A read-only catalog comparison (2026-11-22) found that the live database already has two objects that
-- come from migrations on the main line but not on the deployed line:
--   - tickets.source_message_id -> messages(id) ON DELETE SET NULL      (main: 20261118120000)
--   - account_identities email indexes (lower(email) and email)          (main: 20261116120000)
-- A database built only from the deployed-line migrations lacks them. This file adds them, so that a
-- fresh database matches the live one. On the live database both statements are no-ops in effect:
-- the index statements do nothing when the indexes exist, and the foreign key is replaced with the same
-- definition. The constraint replacement takes a short lock on tickets (a small table) while it re-checks.
--
-- Not included, on purpose: the main-line targeting migration 20261120180000 and knowledge-management
-- migration 20261109150000. Neither is in the live database or on the deployed line, and the targeting
-- one defines course as text while the deployed line uses course_id uuid. That needs a product decision.

create index if not exists account_identities_email_idx on public.account_identities (lower(email));
create index if not exists account_identities_raw_email_idx on public.account_identities (email);

alter table public.tickets drop constraint if exists tickets_source_message_id_fkey;
alter table public.tickets
  add constraint tickets_source_message_id_fkey
  foreign key (source_message_id) references public.messages(id) on delete set null;
