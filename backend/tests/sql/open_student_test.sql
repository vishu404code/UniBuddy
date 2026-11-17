-- Open Student signup: creates only a student with no campus, and refuses duplicates.
do $$
declare
  acct uuid := '7a000000-0000-4000-8000-000000000001';
  result jsonb;
  caught text;
begin
  insert into public.account_identities (id, email) values (acct, 'open.student@example.test');
  set local role service_role;
  result := public.open_student_signup(acct, 'Open.Student@Example.test', 'Open Student');
  reset role;
  if result->>'role' <> 'student' then raise exception 'FAIL: not a student'; end if;
  if (select role || ':' || coalesce(campus_id::text, 'none') from public.profiles where id = acct) <> 'student:none' then
    raise exception 'FAIL: profile is not a campus-less student';
  end if;
  raise notice 'PASS open signup creates a campus-less student';

  begin
    set local role service_role;
    perform public.open_student_signup(acct, 'again@example.test', 'Again');
    reset role;
  exception when others then
    reset role;
    caught := sqlerrm;
  end;
  if caught is null then raise exception 'FAIL: duplicate was accepted'; end if;
  raise notice 'PASS a second signup for the same account is refused';
end $$;
