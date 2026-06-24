-- Baseball shared live draft rooms (PR 4 — Supabase multiplayer)
-- Run in Supabase SQL editor. Service role / RLS policy must allow app writes.

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

-- Optional: enable RLS and add policies for authenticated clients.
-- alter table public.baseball_shared_draft_rooms enable row level security;
