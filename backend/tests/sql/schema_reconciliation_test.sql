-- Schema reconciliation (migration 20261122110000): the objects the live database has must exist.
do $$
begin
  assert (select confdeltype from pg_constraint where conname = 'tickets_source_message_id_fkey') = 'n',
    'tickets.source_message_id must be ON DELETE SET NULL';
  assert exists (select 1 from pg_indexes where schemaname = 'public' and indexname = 'account_identities_email_idx'),
    'account_identities lower(email) index is missing';
  assert exists (select 1 from pg_indexes where schemaname = 'public' and indexname = 'account_identities_raw_email_idx'),
    'account_identities email index is missing';
  raise notice 'PASS reconciled foreign key and identity indexes';
end $$;
