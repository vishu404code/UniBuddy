-- Additive. The course and filter-option routes run as the server role (service_role), but the migrations that
-- created these tables granted access only to the authenticated role, so Authority could not create or read them
-- (HTTP 403 "You are not allowed to do that"). This grants the server role the access its routes use. Students and
-- Faculty still read only through row-level security; the backend keeps the Authority-only write rules.
grant select, insert, update, delete on public.courses to service_role;
grant select, insert, update, delete on public.filter_options to service_role;
