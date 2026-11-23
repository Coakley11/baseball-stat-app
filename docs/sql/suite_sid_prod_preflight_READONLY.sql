-- READ-ONLY production preflight for the suite_sid security response (2026-11-23).
-- Paste the whole file into the Supabase SQL editor of the PRODUCTION project and run it once.
-- Every statement is a SELECT. It returns one table of (section, check, value) rows: counts, dates and
-- privilege flags only. No token, email, user id, IP or row content is returned.

with bridge as (
  select i.*
  from public.suite_saved_items i
  where i.app = '_auth_browser' and i.item_type = 'browser_session'
),
bridge_auth_users as (   -- bridge rows carry the suite_users id or the Auth user id
  select distinct a.id
  from bridge i
  left join public.suite_users u on u.id = i.user_id
  join auth.users a on a.id = i.user_id or (coalesce(u.email, '') <> '' and lower(a.email) = lower(u.email))
),
tables(name) as (
  values ('suite_saved_items'), ('suite_app_current_state'), ('suite_users'), ('suite_user_settings'),
         ('suite_resume_items'), ('suite_activity_events'), ('baseball_shared_draft_rooms'),
         ('baseball_shared_leagues'), ('subscriptions')
),
roles(role) as (values ('anon'), ('authenticated'))
select '1 bridge' as section, 'browser_session rows' as "check", count(*)::text as value from bridge
union all select '1 bridge', 'valid rows', count(*) filter (where valid)::text from bridge
union all select '1 bridge', 'rows holding an access token', count(*) filter (where payload ? 'access_token')::text from bridge
union all select '1 bridge', 'rows holding a refresh token', count(*) filter (where payload ? 'refresh_token')::text from bridge
union all select '1 bridge', 'valid rows holding a refresh token', count(*) filter (where valid and payload ? 'refresh_token')::text from bridge
union all select '1 bridge', 'distinct row owners (user_id)', count(distinct user_id)::text from bridge
union all select '1 bridge', 'distinct owners with a valid token row', count(distinct user_id) filter (where valid and payload ? 'refresh_token')::text from bridge
union all select '1 bridge', 'oldest row', coalesce(min(updated_at)::text, '-') from bridge
union all select '1 bridge', 'newest row', coalesce(max(updated_at)::text, '-') from bridge
union all select '1 bridge', 'rows written in the last 24 h', count(*) filter (where updated_at > now() - interval '24 hours')::text from bridge
union all select '1 bridge', 'rows written in the last 7 days', count(*) filter (where updated_at > now() - interval '7 days')::text from bridge
union all select '1 bridge', 'other saved items (must stay unchanged)', (select count(*) from public.suite_saved_items where not (app = '_auth_browser' and item_type = 'browser_session'))::text
union all select '2 auth', 'Auth accounts linked to bridge rows', (select count(*) from bridge_auth_users)::text
union all select '2 auth', 'their Auth sessions', (select count(*) from auth.sessions s where s.user_id in (select id from bridge_auth_users))::text
union all select '2 auth', 'their Auth sessions not expired', (select count(*) from auth.sessions s where s.user_id in (select id from bridge_auth_users) and (s.not_after is null or s.not_after > now()))::text
union all select '2 auth', 'their unrevoked refresh tokens', (select count(*) from auth.refresh_tokens r join auth.sessions s on s.id = r.session_id where s.user_id in (select id from bridge_auth_users) and not r.revoked)::text
union all select '2 auth', 'all Auth users', (select count(*) from auth.users)::text
union all select '2 auth', 'all Auth sessions', (select count(*) from auth.sessions)::text
union all
select '3 access ' || t.name, r.role || ' privileges / RLS / policies',
       concat_ws(' ',
         nullif(concat_ws(',',
           case when has_table_privilege(r.role, 'public.' || t.name, 'SELECT') then 'SELECT' end,
           case when has_table_privilege(r.role, 'public.' || t.name, 'INSERT') then 'INSERT' end,
           case when has_table_privilege(r.role, 'public.' || t.name, 'UPDATE') then 'UPDATE' end,
           case when has_table_privilege(r.role, 'public.' || t.name, 'DELETE') then 'DELETE' end), ''),
         '| RLS ' || case when c.relrowsecurity then 'ON' else 'OFF' end,
         '| policies ' || (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = t.name
                             and (r.role = any(p.roles) or 'public' = any(p.roles))),
         '| ' || case
           when not (has_table_privilege(r.role, 'public.' || t.name, 'SELECT') or has_table_privilege(r.role, 'public.' || t.name, 'INSERT')
                     or has_table_privilege(r.role, 'public.' || t.name, 'UPDATE') or has_table_privilege(r.role, 'public.' || t.name, 'DELETE'))
             then 'no access'
           when not c.relrowsecurity then 'OPEN: privilege with RLS off'
           else 'RLS-limited (rows only through a policy)' end)
from tables t cross join roles r
join pg_class c on c.relname = t.name and c.relnamespace = 'public'::regnamespace
union all
select '4 policies ' || p.tablename, p.policyname || ' (' || p.cmd || ')',
       'roles=' || array_to_string(p.roles, ',') || ' | using=' || coalesce(left(p.qual, 160), '-') || ' | check=' || coalesce(left(p.with_check, 160), '-')
from pg_policies p
where p.schemaname = 'public'
  and p.tablename in (select name from tables)
  and (p.roles && array['anon', 'authenticated', 'public']::name[])
order by 1, 2;
