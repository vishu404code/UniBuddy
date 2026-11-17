-- Allow deleting messages / conversations without breaking existing tickets
alter table public.tickets
  drop constraint if exists tickets_source_message_id_fkey,
  add constraint tickets_source_message_id_fkey
    foreign key (source_message_id)
    references public.messages(id)
    on delete set null;
