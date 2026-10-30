-- READ-ONLY preflight for the suite_app_current_state ownership migration.
-- Every statement is a SELECT. Nothing here writes, locks or alters. See
-- docs/SUITE_APP_CURRENT_STATE_ISOLATION_PLAN.md for what each result means.
--
-- How to run: the Supabase SQL editor shows only the LAST result set, so run the blocks
-- (P1-P3 ... P12, then P1b and P15) one at a time (highlight one block and run it, or paste it alone). Each block is one statement.
--
-- Safe to share: no metrics, session payloads, tokens, user ids or full emails are returned.
-- Profiles appear as labels: the preset names (daniel, default, ariel, guest, test_user,
-- health_probe, user_unidentified) as they are, any other profile as acct_<6 hex>. That is a
-- pseudonym, not encryption: it hides the profile name in a shared report, nothing more.
-- To map labels back privately (do not share the output):
--   select external_id, 'acct_' || left(md5(external_id), 6) as label from public.suite_users;

-- P1-P3, P11. Schema facts, in one row: version (15+ allows NULLS NOT DISTINCT, alternative B),
-- the primary key, other constraints and indexes, tables referencing this one (must be none for
-- the key swap), RLS, policies, row and owner counts, and which roles bypass RLS.
select current_setting('server_version') as server_version,
       (select pg_get_constraintdef(oid) from pg_constraint
         where conrelid = 'public.suite_app_current_state'::regclass and contype = 'p') as primary_key,
       (select coalesce(string_agg(conname || ' ' || pg_get_constraintdef(oid), ' | ' order by conname), '(none)')
          from pg_constraint
         where conrelid = 'public.suite_app_current_state'::regclass and contype <> 'p') as other_constraints,
       (select string_agg(indexname || ': ' || indexdef, ' | ' order by indexname)
          from pg_indexes where schemaname = 'public' and tablename = 'suite_app_current_state') as indexes,
       (select coalesce(string_agg(conrelid::regclass::text || '.' || conname, ', '), '(none)')
          from pg_constraint where confrelid = 'public.suite_app_current_state'::regclass) as referenced_by,
       c.relrowsecurity as rls_enabled,
       c.relforcerowsecurity as rls_forced,
       (select count(*) from pg_policies where schemaname = 'public' and tablename = 'suite_app_current_state') as policies,
       (select count(*) from public.suite_app_current_state) as total_rows,
       (select count(*) from public.suite_app_current_state where user_id is null) as null_owner_rows,
       (select count(*) from public.suite_app_current_state s
         where s.user_id is not null and not exists (select 1 from public.suite_users u where u.id = s.user_id)) as orphan_owner_rows,
       (select count(distinct user_id) from public.suite_app_current_state) as distinct_owners,
       (select string_agg(rolname || '=' || rolbypassrls, ', ' order by rolname) from pg_roles
         where rolname in ('anon', 'authenticated', 'service_role', 'authenticator')) as bypass_rls
from pg_class c
where c.oid = 'public.suite_app_current_state'::regclass;

-- P4-P7, P14. Every row: its key, the account the key belongs to, the account that owns the row,
-- and the owner stamp a live draft carries inside the saved session. Metadata only.
-- flag (the first problem found per row; anything but 'ok' or 'PRESET_HELD_BY_OWNER' needs a look):
--   P4 NULL_OWNER            no user_id: blocks a (user_id, app) primary key
--   ORPHAN_OWNER             user_id with no suite_users row
--   SHARED_KEY               health_probe / user_unidentified: one key for every account, by design
--   P6 KEY_OWNER_MISMATCH    an unscoped key not owned by daniel/default, or a scoped key "<app>__<ws>"
--                            not owned by profile <ws> (daniel holding a preset is allowed)
--   P14 DRAFT_STAMP_MISMATCH the saved live draft says another profile created it
-- Unscoped rows (the owner's: P7) come first, newest first.
with u as (
  select id, external_id,
         case when external_id in ('daniel', 'default', 'ariel', 'guest', 'test_user', 'health_probe', 'user_unidentified')
              then external_id else 'acct_' || left(md5(external_id), 6) end as label
  from public.suite_users
), s as (
  select st.app, st.updated_at, st.user_id,
         nullif(split_part(st.app, '__', 2), '') as key_ws,
         u.external_id as owner_ext, u.label as owner_label,
         octet_length(st.metrics::text) as metrics_bytes,
         coalesce(jsonb_typeof(st.metrics -> 'full_session') = 'object', false) as has_full_session,
         nullif(coalesce(st.metrics #>> '{full_session,live_draft_state,owner_external_id}',
                         st.metrics #>> '{full_session,live_draft_room,owner_external_id}'), '') as stamp_ext
  from public.suite_app_current_state st
  left join u on u.id = st.user_id
)
select app,
       case when key_ws is null then '(unscoped)'
            when key_ws in ('daniel', 'default', 'ariel', 'guest', 'test_user', 'health_probe', 'user_unidentified') then key_ws
            else 'acct_' || left(md5(key_ws), 6) end as key_workspace,
       coalesce(owner_label, case when user_id is null then '(no owner)' else '(orphan id)' end) as row_owner,
       case when stamp_ext is null then ''
            when stamp_ext in ('daniel', 'default', 'ariel', 'guest', 'test_user', 'health_probe', 'user_unidentified') then stamp_ext
            else 'acct_' || left(md5(stamp_ext), 6) end as draft_owner_stamp,
       updated_at, metrics_bytes, has_full_session,
       case
         when user_id is null then 'P4 NULL_OWNER'
         when owner_ext is null then 'ORPHAN_OWNER'
         when key_ws in ('health_probe', 'user_unidentified') then 'SHARED_KEY'
         when key_ws is null and owner_ext not in ('daniel', 'default') then 'P6 KEY_OWNER_MISMATCH'
         when key_ws is not null and owner_ext <> key_ws
              and not (owner_ext = 'daniel' and key_ws in ('ariel', 'guest', 'test_user')) then 'P6 KEY_OWNER_MISMATCH'
         when stamp_ext is not null and stamp_ext <> owner_ext
              and not (owner_ext = 'default' and stamp_ext = 'daniel')
              and not (stamp_ext = 'daniel' and key_ws in ('ariel', 'guest', 'test_user')) then 'P14 DRAFT_STAMP_MISMATCH'
         when owner_ext = 'daniel' and key_ws in ('ariel', 'guest', 'test_user') then 'PRESET_HELD_BY_OWNER'
         else 'ok'
       end as flag
from s
order by (key_ws is null) desc, updated_at desc;

-- P13. Who else wrote under each state key. Activity events and resume items store the same
-- scoped key with the writer's user_id, and their rows are never taken over, so they keep a
-- history the state row lost. writer_is_row_owner = false means another account wrote under
-- that key; with the key on app alone, that account's state saves went into this same row.
with u as (
  select id,
         case when external_id in ('daniel', 'default', 'ariel', 'guest', 'test_user', 'health_probe', 'user_unidentified')
              then external_id else 'acct_' || left(md5(external_id), 6) end as label
  from public.suite_users
), w as (
  select app, user_id, 'activity_events' as source, count(*) as n, min("timestamp") as first_write, max("timestamp") as last_write
  from public.suite_activity_events group by app, user_id
  union all
  select app, user_id, 'resume_items', count(*), min(updated_at), max(updated_at)
  from public.suite_resume_items group by app, user_id
)
select st.app,
       coalesce(o.label, case when st.user_id is null then '(no owner)' else '(orphan id)' end) as row_owner,
       coalesce(wu.label, case when w.user_id is null then '(no user)' else '(orphan id)' end) as writer,
       w.user_id is not distinct from st.user_id as writer_is_row_owner,
       w.source, w.n, w.first_write, w.last_write
from public.suite_app_current_state st
join w on w.app = st.app
left join u o on o.id = st.user_id
left join u wu on wu.id = w.user_id
order by st.app, writer_is_row_owner, w.last_write desc;

-- P8. Sign-ins the legacy email rule could have mapped onto a preset profile, and every profile.
-- Before 2026-10-27 (and still in the other suite apps) any email containing "daniel" or "ariel"
-- became that profile and shared its suite_users id. Emails are masked to first letter + domain.
with u as (
  select id, email, created_at,
         case when external_id in ('daniel', 'default', 'ariel', 'guest', 'test_user', 'health_probe', 'user_unidentified')
              then external_id else 'acct_' || left(md5(external_id), 6) end as label
  from public.suite_users
)
select 'auth sign-in' as kind,
       left(a.email, 1) || '***@' || split_part(a.email, '@', 2) as masked_email,
       case when a.email ilike '%daniel%' then 'daniel' else 'ariel' end as legacy_rule_profile,
       coalesce((select string_agg(u.label, ', ') from u where lower(u.email) = lower(a.email)),
                '(no profile records this email)') as profile_with_this_email,
       a.created_at, a.last_sign_in_at
from auth.users a
where a.email ilike '%daniel%' or a.email ilike '%ariel%'
union all
select 'suite profile',
       case when coalesce(u.email, '') = '' then '(no email)'
            else left(u.email, 1) || '***@' || split_part(u.email, '@', 2) end,
       null, u.label, u.created_at, null
from u
order by kind, created_at;

-- P9-P10. RLS, policies and anon / authenticated / service_role privileges on every suite and
-- baseball table. Any row with rls_enabled = false and anon or authenticated access is exposed
-- to the public anon key. Exposed tables sort first.
select c.relname as table_name,
       c.relrowsecurity as rls_enabled,
       c.relforcerowsecurity as rls_forced,
       (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as policies,
       has_table_privilege('anon', c.oid, 'SELECT') as anon_read,
       has_table_privilege('anon', c.oid, 'INSERT') or has_table_privilege('anon', c.oid, 'UPDATE')
         or has_table_privilege('anon', c.oid, 'DELETE') as anon_write,
       has_table_privilege('authenticated', c.oid, 'SELECT') as authenticated_read,
       has_table_privilege('authenticated', c.oid, 'INSERT') or has_table_privilege('authenticated', c.oid, 'UPDATE')
         or has_table_privilege('authenticated', c.oid, 'DELETE') as authenticated_write,
       has_table_privilege('service_role', c.oid, 'SELECT') and has_table_privilege('service_role', c.oid, 'INSERT')
         and has_table_privilege('service_role', c.oid, 'UPDATE') and has_table_privilege('service_role', c.oid, 'DELETE') as service_role_full
from pg_class c
where c.relnamespace = 'public'::regnamespace
  and c.relkind in ('r', 'p')
  and (c.relname like 'suite\_%' or c.relname like 'baseball\_%')
order by (c.relrowsecurity
          or not (has_table_privilege('anon', c.oid, 'SELECT') or has_table_privilege('authenticated', c.oid, 'SELECT'))),
         c.relname;

-- P12. Fingerprint of every row. Save this output before any migration phase and compare after
-- it. Hashes only. table_fp uses the same formula as containment C6.
with u as (
  select id,
         case when external_id in ('daniel', 'default', 'ariel', 'guest', 'test_user', 'health_probe', 'user_unidentified')
              then external_id else 'acct_' || left(md5(external_id), 6) end as label
  from public.suite_users
)
select st.app,
       coalesce(u.label, case when st.user_id is null then '(no owner)' else '(orphan id)' end) as row_owner,
       st.updated_at,
       md5(st.metrics::text) as metrics_md5,
       md5(st.page || '|' || st.summary) as page_summary_md5,
       (select md5(coalesce(string_agg(md5(x::text), ',' order by md5(x::text)), ''))
          from public.suite_app_current_state x) as table_fp
from public.suite_app_current_state st
left join u on u.id = st.user_id
order by st.app;

-- P1b. The schema definitions, one line per item: version, columns (type, null, default), every
-- constraint (the primary key included), every index, and every user trigger on the table.
-- Definitions only: no row content. Needed before a migration is proposed.
select 'version' as kind, '' as name, current_setting('server_version') as definition
union all
select 'column', a.attname,
       format_type(a.atttypid, a.atttypmod) || case when a.attnotnull then ' not null' else ' nullable' end
       || coalesce(' default ' || pg_get_expr(d.adbin, d.adrelid), '')
from pg_attribute a
left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
where a.attrelid = 'public.suite_app_current_state'::regclass and a.attnum > 0 and not a.attisdropped
union all
select 'constraint', conname, pg_get_constraintdef(oid)
from pg_constraint where conrelid = 'public.suite_app_current_state'::regclass
union all
select 'index', indexname, indexdef
from pg_indexes where schemaname = 'public' and tablename = 'suite_app_current_state'
union all
select 'trigger', tgname, pg_get_triggerdef(oid)
from pg_trigger where tgrelid = 'public.suite_app_current_state'::regclass and not tgisinternal
order by 1, 2;

-- P15. Who a saved live draft says it belongs to, for every row: the profile and workspace stamps
-- inside metrics.full_session.live_draft_state / live_draft_room. Labels only (preset names as they
-- are, any other profile as acct_<6 hex>); no draft content. A row with no live draft has empty stamps.
-- stamp_vs_owner: 'same' when the stamp names the row's owner; 'DIFFERENT' when it names another
-- profile (the owner's row holds a draft that profile created); '' when there is no stamp.
with u as (
  select id, external_id from public.suite_users
), s as (
  select st.app, st.updated_at, st.user_id, u.external_id as owner_ext,
         jsonb_typeof(st.metrics #> '{full_session,live_draft_state}') = 'object' as has_live_draft_state,
         jsonb_typeof(st.metrics #> '{full_session,live_draft_room}') = 'object' as has_live_draft_room,
         nullif(coalesce(st.metrics #>> '{full_session,live_draft_state,owner_external_id}',
                         st.metrics #>> '{full_session,live_draft_room,owner_external_id}'), '') as stamp_ext,
         nullif(coalesce(st.metrics #>> '{full_session,live_draft_state,owner_workspace_id}',
                         st.metrics #>> '{full_session,live_draft_room,owner_workspace_id}'), '') as stamp_ws
  from public.suite_app_current_state st
  left join u on u.id = st.user_id
)
select app,
       case when owner_ext is null then '(no owner)'
            when owner_ext in ('daniel', 'default', 'ariel', 'guest', 'test_user', 'health_probe', 'user_unidentified') then owner_ext
            else 'acct_' || left(md5(owner_ext), 6) end as row_owner,
       coalesce(has_live_draft_state, false) as has_live_draft_state,
       coalesce(has_live_draft_room, false) as has_live_draft_room,
       case when stamp_ext is null then ''
            when stamp_ext in ('daniel', 'default', 'ariel', 'guest', 'test_user', 'health_probe', 'user_unidentified') then stamp_ext
            else 'acct_' || left(md5(stamp_ext), 6) end as stamp_external_id,
       case when stamp_ws is null then ''
            when stamp_ws in ('daniel', 'default', 'ariel', 'guest', 'test_user', 'health_probe', 'user_unidentified') then stamp_ws
            else 'acct_' || left(md5(stamp_ws), 6) end as stamp_workspace_id,
       case when stamp_ext is null then ''
            when stamp_ext = owner_ext then 'same' else 'DIFFERENT' end as stamp_vs_owner,
       updated_at
from s
order by app;
