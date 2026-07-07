-- Baseball shared league state (Trade System Phase 1)
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

grant usage on schema public to anon, authenticated, service_role;
grant select, insert, update, delete on table public.baseball_shared_leagues to service_role;
grant select, insert, update, delete on table public.baseball_shared_leagues to authenticated;
grant select on table public.baseball_shared_leagues to anon;

notify pgrst, 'reload schema';
