-- DRAFT. NOT APPROVED. DO NOT RUN until the owner approves this exact text.
-- Kept outside supabase/migrations on purpose so no tool applies it.
-- Changes privileges and RLS flags only. No row is read, changed or deleted.
-- service_role (the key every suite app uses for data) bypasses RLS and keeps its own grants,
-- so suite apps are unaffected. Run the read-only preflight first and save C1, C2 and C6.

------------------------------------------------------------------------------
-- Step 1: the three tables open to the public anon role today.
------------------------------------------------------------------------------
begin;
set local lock_timeout = '5s';  -- give up rather than queue behind a long-running query

alter table public.suite_users enable row level security;
alter table public.suite_saved_items enable row level security;
alter table public.suite_user_settings enable row level security;

revoke all on table public.suite_users, public.suite_saved_items, public.suite_user_settings
  from anon, authenticated;

-- The identity sequence behind suite_saved_items.id: anon with UPDATE could setval() it
-- and make every later insert collide.
do $$
declare
  seq text := pg_get_serial_sequence('public.suite_saved_items', 'id');
begin
  if seq is not null then
    execute format('revoke all on sequence %s from anon, authenticated', seq);
  end if;
end
$$;

commit;

------------------------------------------------------------------------------
-- Step 2 (separate approval): the other three already have RLS on with no policies, so
-- anon reads nothing and writes nothing there. Removing the grants is defense in depth.
------------------------------------------------------------------------------
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
