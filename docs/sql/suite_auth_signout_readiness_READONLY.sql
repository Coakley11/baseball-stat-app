-- READ-ONLY readiness check for a one-time sign-out of every Suite user (2026-11-24).
-- Paste into the Supabase SQL editor of the PRODUCTION project and run. Every statement is a SELECT.
-- Returns (section, check, value) rows: counts, flags and constraint actions only. No token, email or id.
-- Use its 'Auth sessions to sign out' value as expected_sessions in suite_auth_global_signout_GUARDED.sql.

with fk as (   -- foreign keys that point at auth.sessions, and what happens to them when a session is deleted
  select c.conrelid::regclass::text as tbl,
         case c.confdeltype when 'c' then 'CASCADE' when 'n' then 'SET NULL' when 'd' then 'SET DEFAULT'
                            when 'r' then 'RESTRICT' else 'NO ACTION' end as on_delete
  from pg_constraint c
  where c.contype = 'f' and c.confrelid = 'auth.sessions'::regclass
)
select * from (
  select '1 privileges' as section, 'running as' as "check", current_user::text as value
  union all select '1 privileges', 'may DELETE auth.sessions', has_table_privilege(current_user, 'auth.sessions', 'DELETE')::text
  union all select '1 privileges', 'may DELETE auth.refresh_tokens', has_table_privilege(current_user, 'auth.refresh_tokens', 'DELETE')::text
  union all select '1 privileges', 'may UPDATE auth.refresh_tokens', has_table_privilege(current_user, 'auth.refresh_tokens', 'UPDATE')::text
  union all select '2 references', 'on delete of a session: ' || tbl, on_delete from fk
  union all select '3 scope', 'Auth sessions to sign out', (select count(*) from auth.sessions)::text
  union all select '3 scope', 'Auth sessions created in the last 24 h', (select count(*) from auth.sessions where created_at > now() - interval '24 hours')::text
  union all select '3 scope', 'accounts with a session', (select count(distinct user_id) from auth.sessions)::text
  union all select '3 scope', 'unrevoked refresh tokens', (select count(*) from auth.refresh_tokens where not revoked)::text
  union all select '3 scope', 'unrevoked refresh tokens without a session (legacy)', (select count(*) from auth.refresh_tokens where not revoked and session_id is null)::text
  union all select '4 unchanged', 'Auth users (must stay)', (select count(*) from auth.users)::text
  union all select '4 unchanged', 'Auth identities (must stay)', (select count(*) from auth.identities)::text
  union all select '4 unchanged', 'public tables fingerprinted (all must stay)', (select count(*) from pg_tables where schemaname = 'public')::text
) x
order by 1, 2;
