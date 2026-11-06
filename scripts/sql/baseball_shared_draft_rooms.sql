-- Baseball shared live draft rooms (PR 4 — Supabase multiplayer)
-- Safe to re-run: creates the table if missing and re-applies the locked-down access below.
-- Run this entire script in the Supabase SQL editor before using Create Shared Draft Room.

create table if not exists public.baseball_shared_draft_rooms (
    room_code text primary key,
    host_user_id text not null default '',
    shared_room_json jsonb not null default '{}'::jsonb,
    revision integer not null default 1,
    status text not null default 'not_started',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists baseball_shared_draft_rooms_status_idx
    on public.baseball_shared_draft_rooms (status);

create index if not exists baseball_shared_draft_rooms_updated_at_idx
    on public.baseball_shared_draft_rooms (updated_at desc);

-- The app reaches this table only with the server-side service-role key.
-- Access: ONLY the app server's service-role key. The browser never reads this table, and
-- anon / authenticated must hold nothing (containment Step B, executed in production 2026-10-31;
-- docs/BASEBALL_SHARED_TABLES_CONTAINMENT.md). Re-running this script keeps it that way: it used
-- to grant anon SELECT and authenticated full access with RLS off, which exposed every row.
grant usage on schema public to service_role;
grant select, insert, update, delete on table public.baseball_shared_draft_rooms to service_role;
alter table public.baseball_shared_draft_rooms enable row level security;
revoke all on table public.baseball_shared_draft_rooms from anon, authenticated;
-- No policies on purpose: with RLS on and no policy, anon and authenticated are refused;
-- service_role bypasses RLS. Do not add policies or grants for anon/authenticated.

notify pgrst, 'reload schema';
