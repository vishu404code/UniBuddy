-- Resolution rate with no tickets (migration 20261108120800). Rolled back at the end.
begin;
delete from public.notifications where ticket_id is not null;
delete from public.ticket_events;
delete from public.tickets;
do $$
begin
  assert (public.management_ticket_stats() -> 'resolution_rate') = 'null'::jsonb,
    'with no tickets the resolution rate must be null, not a number';
  assert (public.management_ticket_stats() -> 'total_tickets') = '0'::jsonb, 'with no tickets the total must be 0';
  raise notice 'PASS zero-ticket resolution rate is null';
end $$;
rollback;
