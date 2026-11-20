-- Ranking fields for private chat memories (rows in chat_summaries). Additive; existing rows get defaults.
--
-- importance: 'normal' (default), 'important' (kept longer), or 'pinned' (kept, ranked first). Set by the
-- Student. use_count and last_used_at record when a memory was used as personal context for an answer.
-- corrected_at is set when the Student corrects the text.
--
-- Writes stay on the server (service role). Students read only their own rows (existing RLS policy).

alter table public.chat_summaries
  add column if not exists importance text not null default 'normal'
    check (importance in ('normal', 'important', 'pinned')),
  add column if not exists use_count integer not null default 0 check (use_count >= 0),
  add column if not exists last_used_at timestamptz,
  add column if not exists corrected_at timestamptz;

create index if not exists chat_summaries_user_importance_idx on public.chat_summaries (user_id, importance);

-- Least privilege: the server may change only the memory fields, never the owner, batch key or message ids.
grant update (summary, importance, use_count, last_used_at, corrected_at) on public.chat_summaries to service_role;
