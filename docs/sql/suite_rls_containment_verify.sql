-- READ-ONLY verification after suite_rls_containment_step1_DRAFT.sql (and step2). Every statement is a SELECT.

-- V1. RLS is on for all six tables. Expect six rows, all true.
select relname, relrowsecurity as rls_enabled
from pg_class
where relnamespace = 'public'::regnamespace and relkind = 'r'
  and relname in ('suite_users', 'suite_saved_items', 'suite_user_settings',
                  'suite_activity_events', 'suite_app_current_state', 'suite_resume_items')
order by relname;

-- V2. anon and authenticated hold nothing; service_role still holds everything the apps use.
-- Expect: anon / authenticated all false (after Step 1: the first three; after Step 2: all six);
-- service_role all true.
select c.relname, r.rolname,
       has_table_privilege(r.rolname, c.oid, 'SELECT') as sel,
       has_table_privilege(r.rolname, c.oid, 'INSERT') as ins,
       has_table_privilege(r.rolname, c.oid, 'UPDATE') as upd,
       has_table_privilege(r.rolname, c.oid, 'DELETE') as del
from pg_class c
cross join (values ('anon'), ('authenticated'), ('service_role')) as r(rolname)
where c.relnamespace = 'public'::regnamespace and c.relkind = 'r'
  and c.relname in ('suite_users', 'suite_saved_items', 'suite_user_settings',
                    'suite_activity_events', 'suite_app_current_state', 'suite_resume_items')
order by c.relname, r.rolname;

-- V3. service_role still bypasses RLS. Expect true.
select rolname, rolbypassrls from pg_roles where rolname = 'service_role';

-- V4. No row changed: rerun preflight C6 and compare every count and fingerprint.
--     (Apps keep writing while you compare, so compare immediately, or compare per table
--     for the tables nobody was using at that moment.)

-- V4b. Only if a C6 fingerprint differs: how many rows each table gained or rewrote since Step 1
-- ran. Replace the timestamp with the time Step 1 was executed (UTC). Counts only, no content.
-- Rows written by the apps since then explain a changed fingerprint for that table. suite_users has
-- no updated_at, so for it a difference with no new rows needs a closer look.
select 'suite_users' as t, count(*) filter (where created_at >= ts) as created_since, null::bigint as written_since
from public.suite_users, (select timestamptz '2026-10-30 00:00:00+00' as ts) p
union all select 'suite_saved_items', null, count(*) filter (where updated_at >= ts)
from public.suite_saved_items, (select timestamptz '2026-10-30 00:00:00+00' as ts) p
union all select 'suite_user_settings', null, count(*) filter (where updated_at >= ts)
from public.suite_user_settings, (select timestamptz '2026-10-30 00:00:00+00' as ts) p
union all select 'suite_activity_events', count(*) filter (where "timestamp" >= ts), null
from public.suite_activity_events, (select timestamptz '2026-10-30 00:00:00+00' as ts) p
union all select 'suite_app_current_state', null, count(*) filter (where updated_at >= ts)
from public.suite_app_current_state, (select timestamptz '2026-10-30 00:00:00+00' as ts) p
union all select 'suite_resume_items', null, count(*) filter (where updated_at >= ts)
from public.suite_resume_items, (select timestamptz '2026-10-30 00:00:00+00' as ts) p;

-- V5. From outside the database (HTTP), with the anon key in an environment variable so it
-- never appears in shell history or the report. Expect a confirmed access denial for each of
-- the three tables: an HTTP 4xx (401 or 403, depending on the gateway) whose JSON body has
-- code "42501" / "permission denied", and no rows. A 200, or a 200 with an empty array, is
-- NOT a pass. The command prints only the status line and the error code, never data:
--   curl -s -H "apikey: $SUPABASE_ANON_KEY" -H "Authorization: Bearer $SUPABASE_ANON_KEY" \
--     -w "\nHTTP %{http_code}\n" "$SUPABASE_URL/rest/v1/suite_saved_items?select=id&limit=1" \
--     | grep -oE '"code":"[^"]*"|HTTP [0-9]+'
--   (repeat for suite_users and suite_user_settings)
--
-- V6. In each suite app (Dev first): sign in, open a page that loads account settings,
-- open a saved item / Continue card, sign out and back in on a second browser. All work.
