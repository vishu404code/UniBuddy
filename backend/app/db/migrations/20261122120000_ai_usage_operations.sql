-- AI usage, extended: summaries and embeddings are metered too, and Management's usage figures count answers only.
--
-- Before this migration ai_usage_events held answer calls only. Chat-summary calls and question and document
-- embeddings were not recorded. The new operations are recorded with token counts when Gemini returns them
-- (embeddings do not return usage here, so their counts stay NULL). Nothing is estimated.
--
-- management_activity_stats is replaced with the same body, except that its usage figures count operation =
-- 'answer' only. Without that, every new row would be reported as an answer.

alter table public.ai_usage_events drop constraint if exists ai_usage_events_operation_check;
alter table public.ai_usage_events
  add constraint ai_usage_events_operation_check
  check (operation in ('answer', 'summary', 'query_embedding', 'document_embedding'));

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
      where operation = 'answer'
  ),
  usage_models as (
    select coalesce(jsonb_agg(distinct model order by model), '[]'::jsonb) as models
      from public.ai_usage_events
      where operation = 'answer'
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
