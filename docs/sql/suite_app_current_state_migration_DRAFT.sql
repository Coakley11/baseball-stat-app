-- DRAFT. NOT APPROVED. DO NOT RUN.
-- Kept outside supabase/migrations on purpose so no tool applies it.
-- Each phase is separate, needs its own approval, and runs only after the read-only
-- preflight (suite_app_current_state_preflight.sql) has been reviewed.
-- None of these statements changes, moves or deletes an existing row.

------------------------------------------------------------------------------
-- Phase 1: no account can take over another account's row (works on today's key).
-- An upsert that would change a row's owner fails instead of replacing the row.
------------------------------------------------------------------------------
create or replace function public.suite_app_current_state_keep_owner()
returns trigger
language plpgsql
as $$
begin
  if new.user_id is distinct from old.user_id then
    raise exception 'suite_app_current_state row % belongs to another account', old.app
      using errcode = '42501';
  end if;
  return new;
end
$$;

create trigger suite_app_current_state_keep_owner
before update on public.suite_app_current_state
for each row execute function public.suite_app_current_state_keep_owner();

-- Phase 1 rollback:
-- drop trigger if exists suite_app_current_state_keep_owner on public.suite_app_current_state;
-- drop function if exists public.suite_app_current_state_keep_owner();

------------------------------------------------------------------------------
-- Phase 2: the per-account unique index. Always succeeds while app is the key,
-- because app alone is already unique. Run on its own (CONCURRENTLY cannot run in a
-- transaction). If the SQL editor refuses CONCURRENTLY, drop that word; the table is small.
------------------------------------------------------------------------------
create unique index concurrently if not exists suite_app_current_state_user_app_key
  on public.suite_app_current_state (user_id, app);

-- Phase 2 rollback:
-- drop index concurrently if exists public.suite_app_current_state_user_app_key;

------------------------------------------------------------------------------
-- Phase 4 (alternative A): the primary key becomes (user_id, app).
-- Only when preflight P4 returned 0 ownerless rows and P3 returned no references,
-- and after the Phase 3 code is deployed to every app that writes this table.
------------------------------------------------------------------------------
begin;
lock table public.suite_app_current_state in share row exclusive mode;
do $$
begin
  if exists (select 1 from public.suite_app_current_state where user_id is null) then
    raise exception 'ownerless rows present: stop and decide per row (plan, Phase 4)';
  end if;
end
$$;
alter table public.suite_app_current_state alter column user_id set not null;
alter table public.suite_app_current_state drop constraint suite_app_current_state_pkey;
alter table public.suite_app_current_state
  add constraint suite_app_current_state_pkey primary key using index suite_app_current_state_user_app_key;
commit;

-- Phase 4 rollback. Possible ONLY while no app key is held by two accounts.
-- Check first; if this returns any row, do not roll the schema back (see the plan):
--   select app, count(*) from public.suite_app_current_state group by app having count(*) > 1;
-- begin;
-- alter table public.suite_app_current_state drop constraint suite_app_current_state_pkey;
-- alter table public.suite_app_current_state add constraint suite_app_current_state_pkey primary key (app);
-- alter table public.suite_app_current_state alter column user_id drop not null;
-- create unique index if not exists suite_app_current_state_user_app_key
--   on public.suite_app_current_state (user_id, app);
-- commit;

------------------------------------------------------------------------------
-- Phase 4 (alternative B): only if ownerless rows exist and must stay as they are.
-- Postgres 15+ only (preflight P1). user_id stays nullable; app stops being unique.
------------------------------------------------------------------------------
-- begin;
-- lock table public.suite_app_current_state in share row exclusive mode;
-- create unique index suite_app_current_state_user_app_nn
--   on public.suite_app_current_state (user_id, app) nulls not distinct;
-- alter table public.suite_app_current_state drop constraint suite_app_current_state_pkey;
-- commit;
-- With no primary key, every upsert must name on_conflict=user_id,app (Phase 3 code).
