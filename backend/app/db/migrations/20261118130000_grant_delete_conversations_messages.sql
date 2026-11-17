-- Grant DELETE and UPDATE on conversations and messages to service_role for conversation deletion
GRANT SELECT, INSERT, UPDATE, DELETE ON public.conversations, public.messages TO service_role;
