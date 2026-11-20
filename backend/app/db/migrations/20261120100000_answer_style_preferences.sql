-- Answer presentation style per Student. Chat history never reaches an answer. This table holds one fixed code
-- per Student, and the server maps that code to presentation text (ANSWER_STYLES in app.ai.rag). It cannot hold
-- free text. Additive. Not applied anywhere yet.

create table if not exists public.chat_answer_preferences (
  user_id uuid primary key references public.profiles(id) on delete cascade,
  style text not null check (style in ('concise', 'plain_language')),
  updated_at timestamptz not null default now()
);

alter table public.chat_answer_preferences enable row level security;

create policy "chat_answer_preferences_select_owner" on public.chat_answer_preferences
  for select to authenticated
  using (user_id = unibuddy_auth.user_id());

-- Students read their own row. Only the server writes it, and only the style column can be set.
revoke all on public.chat_answer_preferences from anon;
grant select on public.chat_answer_preferences to authenticated;
grant select, insert on public.chat_answer_preferences to service_role;
grant update (style, updated_at) on public.chat_answer_preferences to service_role;
