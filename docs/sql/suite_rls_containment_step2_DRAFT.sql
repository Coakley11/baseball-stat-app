-- STEP 2 (separate approval). DRAFT. DO NOT RUN until the owner authorizes this exact text.
-- Defense in depth: these three tables already have RLS on with no policies, so anon reads
-- and writes nothing there today. This removes the unused anon / authenticated grants.
-- Privileges only; no row is touched.

begin;
set local lock_timeout = '5s';

revoke all on table public.suite_activity_events, public.suite_app_current_state, public.suite_resume_items
  from anon, authenticated;

do $$
declare
  t text;
  seq text;
begin
  foreach t in array array['public.suite_activity_events', 'public.suite_resume_items'] loop
    seq := pg_get_serial_sequence(t, 'id');
    if seq is not null then
      execute format('revoke all on sequence %s from anon, authenticated', seq);
    end if;
  end loop;
end
$$;

commit;
