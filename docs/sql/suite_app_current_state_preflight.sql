-- READ-ONLY preflight for the suite_app_current_state ownership migration.
-- Every statement is a SELECT or SHOW. Nothing here writes, locks or alters.
-- See docs/SUITE_APP_CURRENT_STATE_ISOLATION_PLAN.md for what each result means.

-- P1. Postgres version (P15+ allows a NULLS NOT DISTINCT unique index, alternative B).
show server_version;

-- P2. Constraints and indexes on the table.
select conname, contype, pg_get_constraintdef(oid) as definition
from pg_constraint
where conrelid = 'public.suite_app_current_state'::regclass;

select indexname, indexdef
from pg_indexes
where schemaname = 'public' and tablename = 'suite_app_current_state';

-- P3. Anything that references this table (must be empty, or the PK swap needs more care).
select conrelid::regclass as referencing_table, conname
from pg_constraint
where confrelid = 'public.suite_app_current_state'::regclass;

-- P4. Rows with no owner. Must be 0 before the primary key can include user_id.
select count(*) filter (where user_id is null) as null_owner_rows,
       count(*) as total_rows
from public.suite_app_current_state;

select app, updated_at
from public.suite_app_current_state
where user_id is null
order by updated_at desc;

-- P5. Who owns each row. Metadata only: no metrics or session payloads.
select s.app,
       u.external_id as owner_profile,
       s.user_id,
       s.updated_at,
       octet_length(s.metrics::text) as metrics_bytes,
       (s.metrics ? 'full_session') as has_full_session
from public.suite_app_current_state s
left join public.suite_users u on u.id = s.user_id
order by s.app;

-- P6. Rows whose owner does not match the account the key belongs to.
-- An unscoped key ("baseball", "investment", ...) belongs to the owner's profile ("daniel";
-- "default" is the original single-user backfill). A scoped key "<app>__<ws>" belongs to
-- profile <ws>; the owner (daniel) may also hold the demo presets ariel, guest, test_user.
-- Every row returned here needs a human look before anything else happens.
select s.app,
       split_part(s.app, '__', 2) as key_workspace,
       u.external_id as owner_profile,
       s.updated_at
from public.suite_app_current_state s
left join public.suite_users u on u.id = s.user_id
where (position('__' in s.app) = 0
       and coalesce(u.external_id, '') not in ('daniel', 'default'))
   or (position('__' in s.app) > 0
       and coalesce(u.external_id, '') <> split_part(s.app, '__', 2)
       and not (u.external_id = 'daniel'
                and split_part(s.app, '__', 2) in ('ariel', 'guest', 'test_user')))
order by s.app;

-- P7. The owner's unscoped rows, newest first, to compare against the dates the
-- account-isolation bug was live and the dates other accounts were active.
select s.app, u.external_id as owner_profile, s.updated_at
from public.suite_app_current_state s
left join public.suite_users u on u.id = s.user_id
where position('__' in s.app) = 0
order by s.updated_at desc;

-- P8. Profiles and the sign-ins that could have been mapped onto a preset profile.
-- Before 2026-10-27 (and still in the other suite apps) any email containing
-- "daniel" or "ariel" became that profile, sharing its suite_users id.
select external_id, email, created_at
from public.suite_users
order by created_at;

select id, email, created_at, last_sign_in_at
from auth.users
where email ilike '%daniel%' or email ilike '%ariel%'
order by created_at;

-- P9. RLS state and policies for every suite and baseball table, not only this one.
select c.relname as table_name,
       c.relrowsecurity as rls_enabled,
       c.relforcerowsecurity as rls_forced,
       (select count(*) from pg_policies p
         where p.schemaname = 'public' and p.tablename = c.relname) as policy_count
from pg_class c
where c.relnamespace = 'public'::regnamespace
  and c.relkind = 'r'
  and (c.relname like 'suite\_%' or c.relname like 'baseball\_%')
order by c.relname;

-- P10. What the public (anon) and signed-in (authenticated) roles are granted.
-- With RLS off on a table, these grants are all that stands between the anon key and every row.
select table_name, grantee, string_agg(privilege_type, ', ' order by privilege_type) as privileges
from information_schema.role_table_grants
where table_schema = 'public'
  and grantee in ('anon', 'authenticated')
  and (table_name like 'suite\_%' or table_name like 'baseball\_%')
group by table_name, grantee
order by table_name, grantee;

-- P12. Fingerprint of every row, saved before any phase and compared after it.
-- Hashes only; no content is returned.
select app, user_id, updated_at, md5(metrics::text) as metrics_md5
from public.suite_app_current_state
order by app, user_id;

-- P11. Which roles bypass RLS (service_role is expected here).
select rolname, rolbypassrls
from pg_roles
where rolname in ('anon', 'authenticated', 'service_role', 'postgres', 'authenticator');
