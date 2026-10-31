-- Fixture for the two shared Baseball tables, run AFTER suite_rls_fixture.sql. Created exactly as
-- scripts/sql/baseball_shared_draft_rooms.sql and baseball_shared_leagues.sql create them, with the
-- exposure the owner's P9-P10 run found: RLS off, no policies, anon and authenticated may read and
-- write (Supabase's default grants on a new public table are all privileges). Fake data only.
create table public.baseball_shared_draft_rooms (
    room_code text primary key,
    host_user_id text not null default '',
    shared_room_json jsonb not null default '{}'::jsonb,
    revision integer not null default 1,
    status text not null default 'not_started',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index baseball_shared_draft_rooms_status_idx on public.baseball_shared_draft_rooms (status);
create table public.baseball_shared_leagues (
    league_id text primary key,
    draft_fingerprint text not null default '',
    shared_league_json jsonb not null default '{}'::jsonb,
    revision integer not null default 1,
    updated_at timestamptz not null default now(),
    created_at timestamptz not null default now()
);
grant all on table public.baseball_shared_draft_rooms, public.baseball_shared_leagues to anon, authenticated, service_role;

insert into public.baseball_shared_draft_rooms (room_code, host_user_id, shared_room_json, revision, status) values
  ('FAKE-ROOM-1', '00000000-0000-0000-0000-00000000000a', '{"picks": ["fake pick"], "invite": "fake-invite-token"}', 3, 'in_progress'),
  ('FAKE-ROOM-2', '00000000-0000-0000-0000-00000000000b', '{"picks": []}', 1, 'not_started'),
  ('FAKE-ROOM-3', '', '{"picks": ["outsider"]}', 1, 'not_started');
insert into public.baseball_shared_leagues (league_id, draft_fingerprint, shared_league_json, revision) values
  ('FAKE-LEAGUE-1', 'fp1', '{"team_ownership": {"t1": "fake"}, "league_invites": ["fake-invite"]}', 2);

-- Stand-in for the managed auth.users table (D4b only compares ids; the real one is never touched).
create schema if not exists auth;
create table if not exists auth.users (id uuid primary key);
