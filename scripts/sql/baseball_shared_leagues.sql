-- Baseball shared league state (Trade System Phase 1)
-- Safe to re-run: creates the table if missing and re-applies the locked-down access below.
-- Run in Supabase SQL editor before cross-account trades in production.

create table if not exists public.baseball_shared_leagues (
    league_id text primary key,
    draft_fingerprint text not null default '',
    shared_league_json jsonb not null default '{}'::jsonb,
    revision integer not null default 1,
    updated_at timestamptz not null default now(),
    created_at timestamptz not null default now()
);

create index if not exists baseball_shared_leagues_fingerprint_idx
    on public.baseball_shared_leagues (draft_fingerprint);

create index if not exists baseball_shared_leagues_updated_at_idx
    on public.baseball_shared_leagues (updated_at desc);

-- Access: ONLY the app server's service-role key. The browser never reads this table, and
-- anon / authenticated must hold nothing (containment Step B, executed in production 2026-10-31;
-- docs/BASEBALL_SHARED_TABLES_CONTAINMENT.md). Re-running this script keeps it that way: it used
-- to grant anon SELECT and authenticated full access with RLS off, which exposed every row.
grant usage on schema public to service_role;
grant select, insert, update, delete on table public.baseball_shared_leagues to service_role;
alter table public.baseball_shared_leagues enable row level security;
revoke all on table public.baseball_shared_leagues from anon, authenticated;
-- No policies on purpose: with RLS on and no policy, anon and authenticated are refused;
-- service_role bypasses RLS. Do not add policies or grants for anon/authenticated.

notify pgrst, 'reload schema';
