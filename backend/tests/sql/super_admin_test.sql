\set ON_ERROR_STOP on
-- Fixtures (as postgres). Actors: super admin (to be bootstrapped), campus authority, student, management.
insert into public.account_identities (id) values
 ('40000000-0000-4000-8000-000000000001'),('40000000-0000-4000-8000-000000000002'),
 ('40000000-0000-4000-8000-000000000003'),('40000000-0000-4000-8000-000000000004'),
 ('40000000-0000-4000-8000-000000000005');
insert into public.campuses (id, name, code) values
 ('c4000000-0000-4000-8000-000000000001','SA Campus 1','sa1'),
 ('c4000000-0000-4000-8000-000000000002','SA Campus 2','sa2');
insert into public.profiles (id, email, role, campus_id) values
 ('40000000-0000-4000-8000-000000000002','auth.sa@nst.rishihood.edu.in','authority','c4000000-0000-4000-8000-000000000001'),
 ('40000000-0000-4000-8000-000000000003','stud.sa@nst.rishihood.edu.in','student','c4000000-0000-4000-8000-000000000001'),
 ('40000000-0000-4000-8000-000000000004','mgmt.sa@nst.rishihood.edu.in','management','c4000000-0000-4000-8000-000000000001');

-- 1. Bootstrap is refused for a non-university domain, and for an auth user that does not exist.
do $$ declare caught text; begin
  caught := null;
  begin perform public.bootstrap_super_admin('40000000-0000-4000-8000-000000000001', 'root@example.com');
  exception when others then caught := sqlerrm; end;
  assert caught = 'email_domain_not_allowed', 'bootstrap must enforce the university domain: ' || coalesce(caught,'none');

  caught := null;
  begin perform public.bootstrap_super_admin('40000000-0000-4000-8000-0000000000ff', 'root@nst.rishihood.edu.in');
  exception when others then caught := sqlerrm; end;
  assert caught = 'auth_user_not_found', 'bootstrap must require an existing auth user';
  raise notice 'PASS bootstrap refuses bad domain and unknown user';
end $$;

-- 2. Bootstrap once, from the owner's session, for an invited auth user.
insert into public.account_identities (id) values ('40000000-0000-4000-8000-000000000009');
select public.bootstrap_super_admin('40000000-0000-4000-8000-000000000009', 'root@nst.rishihood.edu.in');
do $$ declare caught text; begin
  assert (select role from public.profiles where id = '40000000-0000-4000-8000-000000000009') = 'super_admin', 'bootstrap creates a super_admin profile';
  caught := null;
  begin perform public.bootstrap_super_admin('40000000-0000-4000-8000-000000000001', 'second@nst.rishihood.edu.in');
  exception when others then caught := sqlerrm; end;
  assert caught = 'super_admin_already_exists', 'a second bootstrap must be refused';
  raise notice 'PASS bootstrap runs once';
end $$;

-- 3. The bootstrap function is not executable by any API role.
do $$ declare caught text; begin
  caught := null;
  begin set local role authenticated;
    perform public.bootstrap_super_admin('40000000-0000-4000-8000-000000000001', 'x@nst.rishihood.edu.in');
  exception when others then caught := sqlstate; end;
  reset role;
  assert caught = '42501', 'authenticated must not run the bootstrap';

  caught := null;
  begin set local role service_role;
    perform public.bootstrap_super_admin('40000000-0000-4000-8000-000000000001', 'x@nst.rishihood.edu.in');
  exception when others then caught := sqlstate; end;
  reset role;
  assert caught = '42501', 'service_role must not run the bootstrap';
  raise notice 'PASS bootstrap is owner-only';
end $$;

-- 4. Super Admin provisioning (service path). Authority needs a campus; management may omit it.
set role service_role;
do $$ declare r jsonb; begin
  r := public.super_admin_provision_precheck('40000000-0000-4000-8000-000000000009', 'new.authority@nst.rishihood.edu.in', 'authority', 'c4000000-0000-4000-8000-000000000002');
  assert (r->>'ok')::boolean, 'super admin may provision an authority with a campus';
  r := public.super_admin_provision_precheck('40000000-0000-4000-8000-000000000009', 'new.mgmt@nst.rishihood.edu.in', 'management', null);
  assert (r->>'ok')::boolean, 'super admin may provision management without a campus';
  r := public.super_admin_provision_precheck('40000000-0000-4000-8000-000000000009', 'new.auth2@nst.rishihood.edu.in', 'authority', null);
  assert r->>'reason' = 'campus_required', 'authority without a campus is refused';
  r := public.super_admin_provision_precheck('40000000-0000-4000-8000-000000000009', 'new.stud@nst.rishihood.edu.in', 'student', 'c4000000-0000-4000-8000-000000000001');
  assert r->>'reason' = 'invalid_role', 'super admin cannot provision students here';
  r := public.super_admin_provision_precheck('40000000-0000-4000-8000-000000000002', 'x@nst.rishihood.edu.in', 'management', null);
  assert r->>'reason' = 'not_super_admin', 'a campus authority cannot provision authority or management';
  raise notice 'PASS super admin provisioning rules';
end $$;
reset role;

-- 5. Completion creates the account with the campus the super admin chose, and the audit row.
-- The invite creates the auth user before the profile is completed.
insert into public.account_identities (id) values ('50000000-0000-4000-8000-000000000001');
set role service_role;
do $$ declare caught text; begin
  perform public.super_admin_provision_complete('40000000-0000-4000-8000-000000000009', '50000000-0000-4000-8000-000000000001',
                                                'new.authority@nst.rishihood.edu.in', 'New Authority', 'authority', 'c4000000-0000-4000-8000-000000000002');
  caught := null;
  begin perform public.super_admin_provision_complete('40000000-0000-4000-8000-000000000002', '50000000-0000-4000-8000-000000000002',
                                                      'nope@nst.rishihood.edu.in', 'Nope', 'management', null);
  exception when others then caught := sqlerrm; end;
  assert caught = 'provisioning_not_permitted', 'only super admin may complete these';
  raise notice 'PASS super admin completion';
end $$;
reset role;
do $$ begin
  assert (select campus_id from public.profiles where id = '50000000-0000-4000-8000-000000000001') = 'c4000000-0000-4000-8000-000000000002', 'authority lands on the chosen campus';
  assert (select cross_campus_record_access from public.profiles where id = '50000000-0000-4000-8000-000000000001') = false, 'no cross-campus grant';
  raise notice 'PASS created account has protected campus and no cross-campus grant';
end $$;

-- 6. Super Admin is aggregate and account-only: no academic records through RLS.
select set_config('app.user_id', '40000000-0000-4000-8000-000000000009', false);
set role authenticated;
do $$ begin
  assert (select count(*) from public.profiles) = 1, 'super admin sees only its own profile through RLS';
  assert (select count(*) from public.tickets) = 0, 'super admin reads no tickets';
  assert (select count(*) from public.documents where publication_status <> 'published' or visibility <> 'public_students') = 0, 'super admin reads no drafts or staff documents';
  assert (select count(*) from public.documents) = (select count(*) from public.documents where publication_status = 'published' and visibility = 'public_students'), 'super admin reads only published student-facing documents, as every signed-in user does';
  raise notice 'PASS super admin has no academic-record access';
end $$;
reset role;

-- 7. The account list works for a Super Admin session, returns account fields only, and is refused to others.
select set_config('app.user_id', '40000000-0000-4000-8000-000000000009', false);
set role authenticated;
do $$ declare accounts jsonb; begin
  accounts := public.super_admin_list_accounts();
  assert jsonb_typeof(accounts) = 'array' and jsonb_array_length(accounts) >= 3, 'super admin receives the account list';
  assert accounts::text not like '%academic%' and accounts::text not like '%question%', 'account list carries no academic fields';
  raise notice 'PASS super admin account list (account fields only)';
end $$;
reset role;

select set_config('app.user_id', '40000000-0000-4000-8000-000000000002', false);
set role authenticated;
do $$ declare caught text; begin
  caught := null;
  begin perform public.super_admin_list_accounts();
  exception when others then caught := sqlstate; end;
  assert caught = '42501', 'a campus authority must not read the account list';
  raise notice 'PASS account list refused to a campus authority';
end $$;
reset role;
