-- AI usage operations (migration 20261122120000). Synthetic rows only; the test runs in a rolled-back transaction.
begin;
do $$
declare
  before_rows integer;
  after_rows integer;
  before_answers integer;
  after_answers integer;
begin
  before_rows := (public.management_activity_stats() -> 'gemini' ->> 'rows_recorded')::int;
  before_answers := (public.management_activity_stats() -> 'gemini' ->> 'rows_recorded')::int;

  insert into public.ai_usage_events (operation, model, request_count) values ('summary', 'test-model', 1);
  insert into public.ai_usage_events (operation, model, request_count) values ('query_embedding', 'test-model', 1);
  insert into public.ai_usage_events (operation, model, request_count) values ('document_embedding', 'test-model', 2);

  -- Only answers are reported as answers: the new operations must not change the answer figures.
  after_answers := (public.management_activity_stats() -> 'gemini' ->> 'rows_recorded')::int;
  assert after_answers = before_answers, 'summary and embedding rows must not be counted as answers';

  insert into public.ai_usage_events (operation, model, request_count) values ('answer', 'test-model', 1);
  after_rows := (public.management_activity_stats() -> 'gemini' ->> 'rows_recorded')::int;
  assert after_rows = before_rows + 1, 'an answer row must be counted once';

  begin
    insert into public.ai_usage_events (operation, model, request_count) values ('student question text', 'm', 1);
    raise exception 'an unknown operation was accepted';
  exception when check_violation then
    null;
  end;
  raise notice 'PASS AI usage operations are constrained and only answers are counted as answers';
end $$;
rollback;
