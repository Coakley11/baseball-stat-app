-- Baseball shared live draft rooms (PR 4 — Supabase multiplayer)
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

-- PostgREST / Streamlit app key must be able to read and write this table.
grant usage on schema public to anon, authenticated, service_role;
grant select, insert, update, delete on table public.baseball_shared_draft_rooms to service_role;
grant select, insert, update, delete on table public.baseball_shared_draft_rooms to authenticated;
grant select on table public.baseball_shared_draft_rooms to anon;

-- RLS is optional when using the service_role key (bypasses RLS). If you enable RLS,
-- add policies that allow authenticated clients to read/write their rooms.
-- alter table public.baseball_shared_draft_rooms enable row level security;

notify pgrst, 'reload schema';
