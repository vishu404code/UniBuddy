-- Ticket updates in one transaction. PREPARED, NOT APPLIED.
--
-- A staff update used to write three things in separate requests: the ticket's status or assignee, the
-- timeline events, and the student's notification. A failure between them left a status change without its
-- timeline entry or notification. This function does all three in one database transaction, so either all
-- of them happen or none does.
--
-- Authorization stays in the backend (services/tickets.py: role, assignment and transition rules). Only the
-- backend's service role may call this function. No browser role may.
--
-- p_expected_status guards against a concurrent change: if the ticket is no longer in that status, nothing
-- is written and the function raises ticket_changed.

create or replace function public.apply_ticket_update(
  p_ticket_id uuid,
  p_expected_status text,
  p_status text,
  p_assigned_faculty_id uuid,
  p_events jsonb,
  p_notifications jsonb
)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_status is not null or p_assigned_faculty_id is not null then
    update public.tickets
       set status = coalesce(p_status, status),
           assigned_faculty_id = coalesce(p_assigned_faculty_id, assigned_faculty_id)
     where id = p_ticket_id
       and status = p_expected_status;
    if not found then
      raise exception 'ticket_changed';
    end if;
  end if;

  insert into public.ticket_events (ticket_id, actor_id, event_type, note)
  select p_ticket_id, nullif(e->>'actor_id', '')::uuid, e->>'event_type', e->>'note'
    from jsonb_array_elements(coalesce(p_events, '[]'::jsonb)) as e;

  insert into public.notifications (user_id, text, ticket_id)
  select (n->>'user_id')::uuid, n->>'text', p_ticket_id
    from jsonb_array_elements(coalesce(p_notifications, '[]'::jsonb)) as n;
end;
$$;

revoke execute on function public.apply_ticket_update(uuid, text, text, uuid, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.apply_ticket_update(uuid, text, text, uuid, jsonb, jsonb) to service_role;
