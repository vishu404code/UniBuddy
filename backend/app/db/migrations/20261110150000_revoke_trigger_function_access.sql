-- set_updated_at is a trigger function. It is never called as an API or RPC, so no browser role needs
-- EXECUTE on it. Triggers still fire for ordinary writes. Revoking it closes direct calls by anon and authenticated.
revoke execute on function public.set_updated_at() from public, anon, authenticated;
