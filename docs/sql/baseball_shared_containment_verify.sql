-- READ-ONLY verification after baseball_shared_containment_stepB_DRAFT.sql. Every statement is a SELECT.
-- The SQL editor shows only the last result set: run VB1, VB2, VB3 one at a time.

-- VB1. RLS is on for both tables, and there are no policies. Expect two rows: true, false, 0.
select c.relname as table_name, c.relrowsecurity as rls_enabled, c.relforcerowsecurity as rls_forced,
       (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as policies
from pg_class c
where c.relnamespace = 'public'::regnamespace and c.relkind in ('r', 'p')
  and c.relname in ('baseball_shared_draft_rooms', 'baseball_shared_leagues')
order by c.relname;

-- VB2. anon and authenticated hold nothing; service_role still holds what the app uses.
-- Expect anon / authenticated all false; service_role all true.
select c.relname as table_name, r.rolname as role,
       has_table_privilege(r.rolname, c.oid, 'SELECT') as sel,
       has_table_privilege(r.rolname, c.oid, 'INSERT') as ins,
       has_table_privilege(r.rolname, c.oid, 'UPDATE') as upd,
       has_table_privilege(r.rolname, c.oid, 'DELETE') as del,
       has_table_privilege(r.rolname, c.oid, 'TRUNCATE') as trunc,
       has_table_privilege(r.rolname, c.oid, 'REFERENCES') as refs,
       has_table_privilege(r.rolname, c.oid, 'TRIGGER') as trg,
       has_table_privilege(r.rolname, c.oid, 'MAINTAIN') as maint,
       has_any_column_privilege(r.rolname, c.oid, 'SELECT,INSERT,UPDATE,REFERENCES') as any_column
from pg_class c
cross join (values ('anon'), ('authenticated'), ('service_role')) as r(rolname)
where c.relnamespace = 'public'::regnamespace and c.relkind in ('r', 'p')
  and c.relname in ('baseball_shared_draft_rooms', 'baseball_shared_leagues')
order by c.relname, r.rolname;

-- VB3. Nothing else changed: rerun preflight D4 and compare. n must match; fp matches unless a
-- shared room or league was saved in between (newest_update says when). Apps keep writing, so
-- compare straight away.

-- VB4. From outside the database, with the anonymous REST check (reads the anon key from the
-- clipboard and prints only HTTP status and error code for each table):
--   python -I scripts/sql_tests/anon_rest_denial_check.py
-- Expect HTTP 401 code=42501 for baseball_shared_draft_rooms and baseball_shared_leagues too.
--
-- VB5. In the live Baseball app: create a shared draft room, join it from a second browser, make a
-- pick, open a shared league page and a pending invite. All work (they use the service-role key).
