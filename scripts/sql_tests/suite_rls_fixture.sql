-- Isolated fixture that reproduces the Daniel AI Suite project's suite tables as the owner's
-- 2026-10-30 inspection found them. Fake data only. Never run against a real project.

-- Supabase's API roles. service_role bypasses RLS, as on Supabase.
-- Roles are cluster-wide, so they are created once and reused by every scenario database.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin noinherit;
    create role authenticated nologin noinherit;
    create role service_role nologin noinherit bypassrls;
    create role authenticator login noinherit;
    grant anon, authenticated, service_role to authenticator;
  end if;
end
$$;
grant usage on schema public to anon, authenticated, service_role;

-- Tables, as created by the Command Center migrations 001 and 002.
create table public.suite_users (
  id uuid primary key default gen_random_uuid(),
  external_id text not null unique,
  email text not null default '',
  display_name text not null default '',
  created_at timestamptz not null default current_timestamp
);
create table public.suite_activity_events (
  id bigint generated always as identity primary key,
  app text not null,
  event text not null,
  page text not null default '',
  timestamp timestamptz not null default now(),
  metrics jsonb not null default '{}'::jsonb,
  user_id uuid references public.suite_users (id)
);
create table public.suite_app_current_state (
  app text primary key,
  page text not null default '',
  summary text not null default '',
  metrics jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  user_id uuid references public.suite_users (id)
);
create table public.suite_resume_items (
  id bigint generated always as identity primary key,
  app text not null,
  item_key text not null,
  title text not null,
  subtitle text not null default '',
  action_url text not null default '',
  valid boolean not null default true,
  updated_at timestamptz not null default now(),
  user_id uuid references public.suite_users (id)
);
create unique index idx_suite_resume_user_app_item_key on public.suite_resume_items (user_id, app, item_key);
create table public.suite_saved_items (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.suite_users (id) on delete cascade,
  app text not null,
  item_type text not null default 'item',
  item_key text not null,
  title text not null,
  payload jsonb not null default '{}'::jsonb,
  valid boolean not null default true,
  updated_at timestamptz not null default current_timestamp,
  unique (user_id, app, item_type, item_key)
);
create table public.suite_user_settings (
  user_id uuid not null references public.suite_users (id) on delete cascade,
  app text not null default '_global',
  settings jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default current_timestamp,
  primary key (user_id, app)
);

-- Privileges as found: anon (and, as Supabase's defaults do, authenticated) hold
-- SELECT, INSERT, UPDATE, DELETE; service_role holds everything.
grant select, insert, update, delete on all tables in schema public to anon, authenticated;
grant all on all tables in schema public to service_role;
grant usage, select, update on all sequences in schema public to anon, authenticated;
grant all on all sequences in schema public to service_role;

-- RLS as found: off on three, on (no policies) on three.
alter table public.suite_activity_events enable row level security;
alter table public.suite_app_current_state enable row level security;
alter table public.suite_resume_items enable row level security;

-- Fake accounts and data.
insert into public.suite_users (id, external_id, email, display_name) values
  ('00000000-0000-0000-0000-00000000000a', 'fixture_a', 'a@example.invalid', 'Fixture A'),
  ('00000000-0000-0000-0000-00000000000b', 'fixture_b', 'b@example.invalid', 'Fixture B');
insert into public.suite_saved_items (user_id, app, item_type, item_key, title, payload) values
  ('00000000-0000-0000-0000-00000000000a', '_auth_browser', 'browser_session', 'sid-a', 'session',
   '{"access_token": "fake-access-a", "refresh_token": "fake-refresh-a"}'),
  ('00000000-0000-0000-0000-00000000000b', 'baseball', 'analytical_question_context', 'q1', 'Q', '{"q": "fake"}');
insert into public.suite_user_settings (user_id, app, settings) values
  ('00000000-0000-0000-0000-00000000000a', '_global', '{"league": "fake A league"}'),
  ('00000000-0000-0000-0000-00000000000b', '_global', '{"league": "fake B league"}');
insert into public.suite_app_current_state (app, user_id, metrics) values
  ('baseball', '00000000-0000-0000-0000-00000000000a', '{"full_session": {"board": "fake"}}'),
  ('baseball__fixture_b', '00000000-0000-0000-0000-00000000000b', '{"full_session": {"board": "fake b"}}');
insert into public.suite_activity_events (app, event, user_id) values
  ('baseball', 'fixture', '00000000-0000-0000-0000-00000000000a');
insert into public.suite_resume_items (app, item_key, title, user_id) values
  ('applied_intelligence', 'ai:question:1', 'Continue', '00000000-0000-0000-0000-00000000000a');
