-- READ-ONLY preflight for baseball_shared_containment_stepB_DRAFT.sql.
-- Every statement is a SELECT. Nothing here writes, locks or alters.
-- The SQL editor shows only the LAST result set: run D1, D1b, D2, D3, D4, D5 one at a time.
-- Output is safe to share: catalog facts, counts, dates and hashes only. No room code, league id,
-- invite, draft content, user id or email is returned. Profiles appear as labels (the preset names,
-- or acct_<6 hex> for any other profile).
-- Save D1, D1b, D2 and D4 before running Step B. D2 is the exact rollback.

-- D1. RLS state and every table privilege anon / authenticated / service_role hold on the two tables.
select c.relname as table_name,
       c.relrowsecurity as rls_enabled,
       c.relforcerowsecurity as rls_forced,
       (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as policies,
       r.rolname as role,
       has_table_privilege(r.rolname, c.oid, 'SELECT') as can_select,
       has_table_privilege(r.rolname, c.oid, 'INSERT') as can_insert,
       has_table_privilege(r.rolname, c.oid, 'UPDATE') as can_update,
       has_table_privilege(r.rolname, c.oid, 'DELETE') as can_delete,
       has_table_privilege(r.rolname, c.oid, 'TRUNCATE') as can_truncate,
       has_table_privilege(r.rolname, c.oid, 'REFERENCES') as can_references,
       has_table_privilege(r.rolname, c.oid, 'TRIGGER') as can_trigger
from pg_class c
cross join (values ('anon'), ('authenticated'), ('service_role')) as r(rolname)
where c.relnamespace = 'public'::regnamespace
  and c.relkind in ('r', 'p')
  and c.relname in ('baseball_shared_draft_rooms', 'baseball_shared_leagues')
order by c.relname, r.rolname;

-- D1b. Owner, grantor and who ran this. REVOKE removes only grants made by the role running it.
-- Expect owner = grantor = running_as (normally postgres). A grantee of PUBLIC would be a finding:
-- Step B refuses to run while one exists.
select c.relname as table_name,
       pg_get_userbyid(c.relowner) as owner,
       pg_get_userbyid(a.grantor) as grantor,
       case a.grantee when 0 then 'PUBLIC' else pg_get_userbyid(a.grantee) end as grantee,
       string_agg(a.privilege_type, ', ' order by a.privilege_type) as privileges,
       current_user as running_as
from pg_class c
cross join lateral aclexplode(c.relacl) a
where c.relnamespace = 'public'::regnamespace
  and c.relname in ('baseball_shared_draft_rooms', 'baseball_shared_leagues')
group by c.relname, c.relowner, a.grantor, a.grantee
order by c.relname, grantee;

-- D2. The exact rollback, generated from today's catalog ACLs. Save this output verbatim.
-- (Only grants held directly by anon / authenticated; D1b shows any inherited from PUBLIC.)
select format('grant %s on table public.%I to %I;',
              string_agg(a.privilege_type, ', ' order by a.privilege_type), c.relname, r.rolname) as rollback_statement
from pg_class c
cross join lateral aclexplode(c.relacl) a
join pg_roles r on r.oid = a.grantee
where c.relnamespace = 'public'::regnamespace
  and c.relkind in ('r', 'p')
  and c.relname in ('baseball_shared_draft_rooms', 'baseball_shared_leagues')
  and r.rolname in ('anon', 'authenticated')
group by c.oid, c.relname, r.rolname
union all
select format('alter table public.%I disable row level security;', relname)
from pg_class
where relnamespace = 'public'::regnamespace and relkind in ('r', 'p') and not relrowsecurity
  and relname in ('baseball_shared_draft_rooms', 'baseball_shared_leagues');

-- D3. Other access paths to the same data, one row of counts. Step B refuses to run if any of the
-- first four is non-zero (or if there is a serial column); the rest are for review.
select (select count(distinct v.oid) from pg_depend d
          join pg_rewrite rw on rw.oid = d.objid join pg_class v on v.oid = rw.ev_class
         where d.refobjid in ('public.baseball_shared_draft_rooms'::regclass, 'public.baseball_shared_leagues'::regclass)
           and v.oid <> d.refobjid
           and (has_table_privilege('anon', v.oid, 'SELECT,INSERT,UPDATE,DELETE')
                or has_table_privilege('authenticated', v.oid, 'SELECT,INSERT,UPDATE,DELETE'))) as views_open_to_api_roles,
       (select count(*) from pg_proc pr join pg_namespace n on n.oid = pr.pronamespace
         where n.nspname not in ('pg_catalog', 'information_schema') and pr.prosecdef
           and pr.prosrc ~* 'baseball_shared_(draft_rooms|leagues)'
           and (has_function_privilege('anon', pr.oid, 'EXECUTE')
                or has_function_privilege('authenticated', pr.oid, 'EXECUTE'))) as definer_functions_open_to_api_roles,
       (select count(*) from pg_class c cross join lateral aclexplode(c.relacl) a
         where c.relnamespace = 'public'::regnamespace
           and c.relname in ('baseball_shared_draft_rooms', 'baseball_shared_leagues') and a.grantee = 0) as public_grants,
       (select count(*) from pg_attribute a join pg_class c on c.oid = a.attrelid
         where c.relnamespace = 'public'::regnamespace
           and c.relname in ('baseball_shared_draft_rooms', 'baseball_shared_leagues')
           and a.attnum > 0 and not a.attisdropped
           and pg_get_serial_sequence('public.' || c.relname, a.attname) is not null) as serial_columns,
       (select count(*) from pg_proc pr join pg_namespace n on n.oid = pr.pronamespace
         where n.nspname not in ('pg_catalog', 'information_schema')
           and pr.prosrc ~* 'baseball_shared_(draft_rooms|leagues)') as functions_naming_tables,
       (select count(*) from pg_publication_tables
         where schemaname = 'public' and tablename in ('baseball_shared_draft_rooms', 'baseball_shared_leagues')) as in_publications,
       (select count(*) from pg_trigger
         where tgrelid in ('public.baseball_shared_draft_rooms'::regclass, 'public.baseball_shared_leagues'::regclass)
           and not tgisinternal) as user_triggers;

-- D4. What is in the two tables, without any content: row counts, date ranges, revision, size, who
-- the rooms say their host is, and a content fingerprint (same formula as the suite C6) to compare
-- after Step B. hosts_unrecognised counts rooms whose host_user_id is empty or matches no profile:
-- rows an outsider might have created would look like that. Save this output.
with u as (
  select id::text as id_text,
         case when external_id in ('daniel', 'default', 'ariel', 'guest', 'test_user', 'health_probe', 'user_unidentified')
              then external_id else 'acct_' || left(md5(external_id), 6) end as label
  from public.suite_users
), rooms as (
  select r.status, coalesce(u.label, case when r.host_user_id = '' then '(empty)' else '(unknown id)' end) as host_label
  from public.baseball_shared_draft_rooms r
  left join u on u.id_text = r.host_user_id
)
select 'baseball_shared_draft_rooms' as table_name,
       count(*) as n,
       min(x.created_at) as oldest_created, max(x.created_at) as newest_created, max(x.updated_at) as newest_update,
       max(x.revision) as max_revision,
       min(octet_length(x.shared_room_json::text)) as min_json_bytes, max(octet_length(x.shared_room_json::text)) as max_json_bytes,
       (select string_agg(host_label || '=' || c, ', ' order by host_label)
          from (select host_label, count(*) as c from rooms group by 1) h) as hosts,
       (select count(*) from rooms where host_label in ('(empty)', '(unknown id)')) as hosts_unrecognised,
       (select string_agg(status || '=' || c, ', ' order by status)
          from (select status, count(*) as c from rooms group by 1) s) as detail,
       md5(coalesce(string_agg(md5(x::text), ',' order by md5(x::text)), '')) as fp
from public.baseball_shared_draft_rooms x
union all
select 'baseball_shared_leagues', count(*),
       min(x.created_at), max(x.created_at), max(x.updated_at), max(x.revision),
       min(octet_length(x.shared_league_json::text)), max(octet_length(x.shared_league_json::text)),
       null, null,
       'distinct_draft_fingerprints=' || count(distinct x.draft_fingerprint),
       md5(coalesce(string_agg(md5(x::text), ',' order by md5(x::text)), ''))
from public.baseball_shared_leagues x;

-- D5. When each row was last updated, by month, beside how many Baseball events the suite logged
-- that month. A month with rows last updated but no Baseball activity at all is worth a look.
-- (A row keeps only its LAST update, so this under-reports older edits.)
with m as (
  select t.table_name, date_trunc('month', t.updated_at) as month, count(*) as rows_last_updated
  from (select 'baseball_shared_draft_rooms' as table_name, updated_at from public.baseball_shared_draft_rooms
        union all
        select 'baseball_shared_leagues', updated_at from public.baseball_shared_leagues) t
  group by 1, 2
)
select m.table_name, m.month::date as month, m.rows_last_updated,
       (select count(*) from public.suite_activity_events e
         where e.app like 'baseball%' and date_trunc('month', e."timestamp") = m.month) as baseball_events_that_month
from m
order by m.table_name, m.month;

-- D4b. What identity format does host_user_id hold, and does it match any known account? READ-ONLY, counts only.
-- The app writes host_user_id from one of three places: the Supabase Auth user UUID (auth.users.id), the suite
-- account id (suite_users.id), or the participant id of an anonymous visitor. D4 only matched suite_users.id, so
-- "(unknown id)" can simply mean an Auth UUID or a participant id. This classifies each room by format and by
-- which identity set it matches. It selects only ids from auth.users to compare them and returns no id, code,
-- email or content.
select case when r.host_user_id = '' then 'empty'
            when r.host_user_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' then 'uuid-shaped'
            else 'other text, ' || length(r.host_user_id) || ' chars' end as host_format,
       exists (select 1 from public.suite_users u where u.id::text = r.host_user_id) as matches_suite_users_id,
       exists (select 1 from public.suite_users u where u.external_id = r.host_user_id) as matches_suite_external_id,
       exists (select 1 from auth.users a where a.id::text = r.host_user_id) as matches_auth_user_id,
       r.host_user_id = coalesce(r.shared_room_json->>'host_participant_id', '') as equals_host_participant_id,
       to_char(r.created_at, 'YYYY-MM') as created_month,
       r.status,
       count(*) as rooms
from public.baseball_shared_draft_rooms r
group by 1, 2, 3, 4, 5, 6, 7
order by created_month, rooms desc;
