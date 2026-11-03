-- ROLLBACK for baseball_shared_containment_stepB_DRAFT.sql. DRAFT. Do not run unless a legitimate
-- client breaks. Rolling back RE-OPENS the exposure: the public anon key can again read and write
-- every shared draft room and league.
--
-- Preferred: run the statements that preflight D2 generated (saved before Step B), verbatim, in one
-- transaction. They restore exactly the privileges and RLS flags that existed.
--
-- Fallback if D2 was not saved. The owner's P9-P10 inspection showed anon and authenticated could
-- read and write both tables with RLS off; Supabase's default grants are all privileges. This
-- restores that.
begin;
grant all on table public.baseball_shared_draft_rooms to anon, authenticated;
grant all on table public.baseball_shared_leagues to anon, authenticated;
alter table public.baseball_shared_draft_rooms disable row level security;
alter table public.baseball_shared_leagues disable row level security;
commit;
