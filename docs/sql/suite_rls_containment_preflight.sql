-- READ-ONLY preflight for the suite RLS containment (suite_rls_containment_step1_DRAFT.sql, step2).
-- Every statement is a SELECT. Nothing here writes, locks or alters, and no row content
-- is returned: only catalog facts, counts and hashes.
-- Save the output of C1, C2 and C6 before containment. C2 is the exact rollback.

-- C1. Current RLS state and every privilege anon / authenticated / service_role hold on
-- the six suite tables and their sequences.
select c.relname as object,
       case c.relkind when 'S' then 'sequence' else 'table' end as kind,
       c.relrowsecurity as rls_enabled,
       c.relforcerowsecurity as rls_forced,
       r.rolname as role,
       has_table_privilege(r.rolname, c.oid, 'SELECT') as can_select,
       has_table_privilege(r.rolname, c.oid, 'INSERT') as can_insert,
       has_table_privilege(r.rolname, c.oid, 'UPDATE') as can_update,
       has_table_privilege(r.rolname, c.oid, 'DELETE') as can_delete
from pg_class c
cross join (values ('anon'), ('authenticated'), ('service_role')) as r(rolname)
where c.relnamespace = 'public'::regnamespace
  and c.relkind = 'r'
  and c.relname in ('suite_users', 'suite_saved_items', 'suite_user_settings',
                    'suite_activity_events', 'suite_app_current_state', 'suite_resume_items')
order by c.relname, r.rolname;

select s.relname as sequence, r.rolname as role,
       has_sequence_privilege(r.rolname, s.oid, 'USAGE') as can_use,
       has_sequence_privilege(r.rolname, s.oid, 'UPDATE') as can_setval
from pg_class s
cross join (values ('anon'), ('authenticated'), ('service_role')) as r(rolname)
where s.relnamespace = 'public'::regnamespace and s.relkind = 'S' and s.relname like 'suite\_%'
order by s.relname, r.rolname;

-- C1b. Who owns the three tables and who granted anon / authenticated their access.
-- REVOKE removes only grants made by the role running it (the owner, when run as owner or
-- superuser). Expect owner = grantor = the role the SQL editor runs as (normally postgres).
-- If a grantor differs, Step 1 still refuses safely after the change (its proof finds the
-- leftover privilege and undoes everything); tell Claude, and the revoke is adjusted.
select c.relname as table_name,
       pg_get_userbyid(c.relowner) as owner,
       pg_get_userbyid(a.grantor) as grantor,
       case a.grantee when 0 then 'PUBLIC' else pg_get_userbyid(a.grantee) end as grantee,
       string_agg(a.privilege_type, ', ' order by a.privilege_type) as privileges,
       current_user as running_as
from pg_class c
cross join lateral aclexplode(c.relacl) a
where c.oid in ('public.suite_users'::regclass, 'public.suite_saved_items'::regclass,
                'public.suite_user_settings'::regclass)
  and (a.grantee = 0 or pg_get_userbyid(a.grantee) in ('anon', 'authenticated'))
group by c.relname, c.relowner, a.grantor, a.grantee
order by c.relname, grantee;

-- C2. The exact rollback, generated from today's catalog ACLs (every privilege, including
-- sequence SELECT/UPDATE, which information_schema does not report). Save this output verbatim.
-- (Only grants held directly by anon / authenticated; C1 shows any inherited from PUBLIC.)
select format('grant %s on %s public.%I to %I;',
              string_agg(a.privilege_type, ', ' order by a.privilege_type),
              case c.relkind when 'S' then 'sequence' else 'table' end,
              c.relname, r.rolname) as rollback_statement
from pg_class c
cross join lateral aclexplode(c.relacl) a
join pg_roles r on r.oid = a.grantee
where c.relnamespace = 'public'::regnamespace
  and c.relkind in ('r', 'S')
  and c.relname like 'suite\_%'
  and r.rolname in ('anon', 'authenticated')
group by c.oid, c.relkind, r.rolname
union all
select format('alter table public.%I disable row level security;', relname)
from pg_class
where relnamespace = 'public'::regnamespace and relkind = 'r' and not relrowsecurity
  and relname in ('suite_users', 'suite_saved_items', 'suite_user_settings',
                  'suite_activity_events', 'suite_app_current_state', 'suite_resume_items');

-- C3. Other access paths to the same data.
-- C3a. Views or materialized views built on the six tables, and whether anon can read them.
select distinct v.oid::regclass as view_name, d.refobjid::regclass as base_table,
       has_table_privilege('anon', v.oid, 'SELECT') as anon_can_select,
       coalesce(v.reloptions::text, '') as options  -- security_invoker=true respects RLS
from pg_depend d
join pg_rewrite rw on rw.oid = d.objid
join pg_class v on v.oid = rw.ev_class
where d.refobjid in ('public.suite_users'::regclass, 'public.suite_saved_items'::regclass,
                     'public.suite_user_settings'::regclass, 'public.suite_activity_events'::regclass,
                     'public.suite_app_current_state'::regclass, 'public.suite_resume_items'::regclass)
  and v.oid <> d.refobjid;

-- C3b. Functions whose body names one of the tables, whether they run as their owner
-- (security definer bypasses the caller's grants and RLS), and whether anon can call them.
select p.oid::regprocedure as function_name, p.prosecdef as security_definer,
       has_function_privilege('anon', p.oid, 'EXECUTE') as anon_can_execute,
       has_function_privilege('authenticated', p.oid, 'EXECUTE') as authenticated_can_execute
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname not in ('pg_catalog', 'information_schema')
  and p.prosrc ~* 'suite_(users|saved_items|user_settings|activity_events|app_current_state|resume_items)';

-- C3c. Realtime publication (anon subscribers receive changes of tables with RLS off).
select pubname, schemaname, tablename
from pg_publication_tables
where tablename like 'suite\_%';

-- C3d. GraphQL endpoint (pg_graphql follows the same grants, so the revoke covers it).
select extname, extversion from pg_extension where extname = 'pg_graphql';

-- C3e. Schemas the Data API serves (if set on the role; otherwise see Dashboard > API settings).
select rolname, rolconfig from pg_roles where rolname = 'authenticator';

-- C4. Every OTHER object in public that anon can reach with RLS off (not only suite tables).
select c.relname, c.relkind, c.relrowsecurity as rls_enabled,
       has_table_privilege('anon', c.oid, 'SELECT') as anon_select,
       has_table_privilege('anon', c.oid, 'INSERT,UPDATE,DELETE') as anon_write
from pg_class c
where c.relnamespace = 'public'::regnamespace
  and c.relkind in ('r', 'p', 'v', 'm', 'f')
  and not c.relrowsecurity
  and has_table_privilege('anon', c.oid, 'SELECT,INSERT,UPDATE,DELETE')
order by c.relname;

-- C5. Do the stored browser sessions hold sign-in tokens? Counts only, no values.
select count(*) as browser_session_rows,
       count(*) filter (where payload ? 'refresh_token') as rows_with_refresh_token,
       max(updated_at) as newest
from public.suite_saved_items
where app = '_auth_browser' and item_type = 'browser_session';

-- C6. Content fingerprints, compared after containment to prove no row changed.
select 'suite_users' as t, count(*) as n, md5(coalesce(string_agg(md5(x::text), ',' order by md5(x::text)), '')) as fp from public.suite_users x
union all select 'suite_saved_items', count(*), md5(coalesce(string_agg(md5(x::text), ',' order by md5(x::text)), '')) from public.suite_saved_items x
union all select 'suite_user_settings', count(*), md5(coalesce(string_agg(md5(x::text), ',' order by md5(x::text)), '')) from public.suite_user_settings x
union all select 'suite_activity_events', count(*), md5(coalesce(string_agg(md5(x::text), ',' order by md5(x::text)), '')) from public.suite_activity_events x
union all select 'suite_app_current_state', count(*), md5(coalesce(string_agg(md5(x::text), ',' order by md5(x::text)), '')) from public.suite_app_current_state x
union all select 'suite_resume_items', count(*), md5(coalesce(string_agg(md5(x::text), ',' order by md5(x::text)), '')) from public.suite_resume_items x;

-- C7. Which apps already write through an RLS-bypassing key. suite_app_current_state and
-- suite_activity_events have RLS on with no policies, so only a bypassing key can write them:
-- an app with recent rows here does not depend on anon access.
select split_part(app, '__', 1) as app, max(updated_at) as last_state_write
from public.suite_app_current_state group by 1 order by 1;

select split_part(app, '__', 1) as app, max(timestamp) as last_event_write
from public.suite_activity_events group by 1 order by 1;
