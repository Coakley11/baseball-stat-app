-- READ-ONLY (SELECT only). Run in the baseball-qa-staging SQL editor only. Nothing is changed.
-- What the REST probe cannot see: every public table with RLS state and policy count, every policy on
-- the tables these tests use, the columns of those tables, and auth-users triggers.
select 'A_table' as section, c.relname as item,
       concat_ws(' | ', 'rls ' || case when c.relrowsecurity then 'ON' else 'off' end,
                        'policies ' || (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname)::text,
                        'est rows ' || greatest(c.reltuples, 0)::bigint::text) as value
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r'
union all
select 'B_policy', p.tablename || ' / ' || p.policyname,
       concat_ws(' | ', p.cmd, 'roles ' || array_to_string(p.roles, ','), 'using ' || coalesce(left(p.qual, 80), '-'))
from pg_policies p
where p.schemaname = 'public'
union all
select 'C_column', table_name || '.' || column_name, data_type || case when is_nullable = 'NO' then ' not null' else '' end
from information_schema.columns
where table_schema = 'public'
  and table_name in ('suite_users', 'suite_app_current_state', 'suite_user_settings', 'suite_activity_events',
                     'baseball_shared_draft_rooms', 'baseball_shared_leagues')
union all
select 'D_auth_trigger', tgname, pg_get_triggerdef(t.oid)
from pg_trigger t join pg_class c on c.oid = t.tgrelid join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'auth' and c.relname = 'users' and not t.tgisinternal
union all
select 'E_counts', 'auth.users', (select count(*) from auth.users)::text
order by 1, 2;
