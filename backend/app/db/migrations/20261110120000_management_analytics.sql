-- Management analytics: aggregate counts only, and Gemini usage metadata for answers.
--
-- ai_usage_events holds no question text, answer text, user id or email. One row is one
-- successful Gemini answer call: when it happened, the model, and the token counts Gemini returned.
-- A count is NULL when Gemini did not return it. Nothing is estimated.
--
-- Usage was not recorded before this table existed, so there is no historical usage to report.

create table public.ai_usage_events (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  operation text not null check (operation in ('answer')),
  model text not null,
  request_count integer not null default 1 check (request_count >= 0),
  input_tokens integer check (input_tokens is null or input_tokens >= 0),
  output_tokens integer check (output_tokens is null or output_tokens >= 0)
);

create index ai_usage_events_created_at_idx on public.ai_usage_events(created_at);

alter table public.ai_usage_events enable row level security;
-- Only the backend (service_role) writes and reads this table. No browser role can see it.
revoke all on public.ai_usage_events from public, anon, authenticated;
grant select, insert on public.ai_usage_events to service_role;

-- Aggregates for the Management portal. Returns counts and sums only: no names, emails, or text.
-- SECURITY DEFINER with a fixed search_path so it can count across campuses. Only service_role may
-- run it, and the backend allows it only for the management role.
create or replace function public.management_activity_stats()
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  with bounds as (
    select (now() at time zone 'UTC')::date as today
  ),
  days as (
    select generate_series(b.today - 29, b.today, interval '1 day')::date as day
      from bounds b
  ),
  questions as (
    select (m.created_at at time zone 'UTC')::date as day, count(*) as n
      from public.messages m
     where m.role = 'user'
     group by 1
  ),
  ticket_days as (
    select (t.created_at at time zone 'UTC')::date as day, count(*) as n
      from public.tickets t
     group by 1
  ),
  usage_totals as (
    select count(*) as rows_recorded,
           coalesce(sum(request_count), 0) as requests,
           count(input_tokens) as rows_with_input_tokens,
           count(output_tokens) as rows_with_output_tokens,
           sum(input_tokens) as input_tokens,
           sum(output_tokens) as output_tokens,
           min(created_at) as first_recorded_at,
           max(created_at) as last_recorded_at
      from public.ai_usage_events
  ),
  usage_models as (
    select coalesce(jsonb_agg(distinct model order by model), '[]'::jsonb) as models
      from public.ai_usage_events
  )
  select jsonb_build_object(
    'questions_total', (select coalesce(sum(n), 0) from questions),
    'questions_by_day', (
      select coalesce(jsonb_agg(jsonb_build_object('day', d.day, 'count', coalesce(q.n, 0)) order by d.day), '[]'::jsonb)
        from days d left join questions q on q.day = d.day
    ),
    'tickets_by_day', (
      select coalesce(jsonb_agg(jsonb_build_object('day', d.day, 'count', coalesce(t.n, 0)) order by d.day), '[]'::jsonb)
        from days d left join ticket_days t on t.day = d.day
    ),
    'gemini', jsonb_build_object(
      'operation', 'answer',
      'first_recorded_at', (select first_recorded_at from usage_totals),
      'last_recorded_at', (select last_recorded_at from usage_totals),
      'rows_recorded', (select rows_recorded from usage_totals),
      'requests', (select requests from usage_totals),
      'rows_with_input_tokens', (select rows_with_input_tokens from usage_totals),
      'rows_with_output_tokens', (select rows_with_output_tokens from usage_totals),
      'input_tokens', (select input_tokens from usage_totals),
      'output_tokens', (select output_tokens from usage_totals),
      'models', (select models from usage_models)
    ),
    'generated_at', now()
  );
$$;

revoke execute on function public.management_activity_stats() from public, anon, authenticated;
grant execute on function public.management_activity_stats() to service_role;
