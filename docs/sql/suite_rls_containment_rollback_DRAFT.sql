-- DRAFT rollback for suite_rls_containment_DRAFT.sql. NOT APPROVED. DO NOT RUN.
-- Rolling back RE-OPENS the exposure (including stored sign-in tokens). Use it only if a
-- legitimate client breaks, and prefer fixing that client to rolling back.
--
-- Preferred: run the statements preflight C2 generated before containment, verbatim, in
-- one transaction. They restore exactly what existed.
--
-- Fallback, matching the owner's 2026-10-30 inspection (anon held SELECT, INSERT, UPDATE,
-- DELETE; RLS off on the first three tables). If C2 also listed authenticated grants or
-- other privileges, use C2 instead of this.

-- Step 1 rollback
begin;
set local lock_timeout = '5s';
alter table public.suite_users disable row level security;
alter table public.suite_saved_items disable row level security;
alter table public.suite_user_settings disable row level security;
grant select, insert, update, delete
  on table public.suite_users, public.suite_saved_items, public.suite_user_settings
  to anon;
commit;

-- Step 2 rollback (RLS stays on: it was already on before containment)
begin;
set local lock_timeout = '5s';
grant select, insert, update, delete
  on table public.suite_activity_events, public.suite_app_current_state, public.suite_resume_items
  to anon;
commit;

-- Sequence grants: restore only from preflight C2 (exact names and privileges).
