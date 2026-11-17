-- Private summaries of older Student chats.
--
-- Additive. A summary is a short note of useful key points from raw messages that are older than the
-- 72-hour chat window. It is written by the backend (secret key) before the raw messages are deleted.
--
-- Access: only the Student who owns the chat can read its summaries (RLS). No other role, Management
-- included, can read them, and nothing in the API shows a summary as a transcript.
--
-- conversation_id has no foreign key: the conversation may be removed once it has no messages left.
-- batch_key identifies the exact set of messages a summary covers. A unique (user_id, batch_key) makes
-- a retry return the existing summary instead of creating a second one.

create table public.chat_summaries (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  conversation_id uuid,
  batch_key text not null check (char_length(batch_key) = 64),
  message_count integer not null check (message_count > 0),
  first_message_at timestamptz not null,
  last_message_at timestamptz not null,
  summary text not null check (char_length(btrim(summary)) between 1 and 1500),
  created_at timestamptz not null default now(),
  constraint chat_summaries_user_batch_key unique (user_id, batch_key)
);

create index chat_summaries_user_last_idx on public.chat_summaries (user_id, last_message_at desc);

alter table public.chat_summaries enable row level security;

create policy "chat_summaries_select_owner" on public.chat_summaries
  for select to authenticated
  using (user_id = unibuddy_auth.user_id());

revoke all on public.chat_summaries from anon;
grant select on public.chat_summaries to authenticated;
grant select, insert, delete on public.chat_summaries to service_role;

-- The 72-hour window reads messages by time and conversations by their last activity.
create index if not exists messages_created_at_idx on public.messages (created_at);
create index if not exists conversations_user_updated_idx on public.conversations (user_id, updated_at desc);
