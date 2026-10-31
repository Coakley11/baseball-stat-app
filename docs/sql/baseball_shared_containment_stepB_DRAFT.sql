-- STEP B CONTAINMENT. All preflight (D1-D5) passed. DO NOT RUN until the owner approves this exact text.
-- Closes anon / authenticated access to baseball_shared_draft_rooms and baseball_shared_leagues.
--
-- One statement (a DO block), so it is atomic in any client, including the Supabase SQL editor:
-- if any check below fails, nothing is changed. It changes RLS flags and privileges only.
-- It reads no row content, changes or deletes no row, and does not touch the auth schema,
-- any other table, or any service_role grant.

do $containment$
declare
  tables constant text[] := array['public.baseball_shared_draft_rooms', 'public.baseball_shared_leagues'];
  api_roles constant text[] := array['anon', 'authenticated'];
  t text;
  r text;
  p text;
  problem text;
  service_role_before text;
  service_role_after text;
begin
  -- Give up (and change nothing) rather than wait behind a long-running query.
  perform set_config('lock_timeout', '5s', true);

  ----------------------------------------------------------------------------
  -- Checks before any change
  ----------------------------------------------------------------------------
  -- 1. service_role bypasses RLS and holds its own read/write on both tables.
  if not exists (select 1 from pg_roles where rolname = 'service_role' and rolbypassrls) then
    raise exception 'ABORTED, nothing changed: service_role is missing or does not bypass RLS';
  end if;
  foreach t in array tables loop
    foreach p in array array['SELECT', 'INSERT', 'UPDATE', 'DELETE'] loop
      if not has_table_privilege('service_role', t, p) then
        raise exception 'ABORTED, nothing changed: service_role lacks % on %', p, t;
      end if;
    end loop;
  end loop;

  -- 2. No grant to PUBLIC (every role inherits it; a revoke from anon would not remove it).
  select string_agg(c.oid::regclass::text, ', ') into problem
  from pg_class c
  cross join lateral aclexplode(c.relacl) a
  where c.oid = any (tables::regclass[]) and a.grantee = 0;
  if problem is not null then
    raise exception 'ABORTED, nothing changed: PUBLIC holds privileges on %', problem;
  end if;

  -- 3. anon / authenticated do not reach the tables through a role they belong to.
  with recursive member_of(role_oid) as (
    select m.roleid from pg_auth_members m
    where m.member in ('anon'::regrole, 'authenticated'::regrole)
    union
    select m.roleid from pg_auth_members m join member_of on m.member = member_of.role_oid
  )
  select string_agg(distinct pg_get_userbyid(role_oid), ', ') into problem
  from member_of
  where exists (
    select 1 from unnest(tables) as x(tbl)
    where has_table_privilege(role_oid, x.tbl, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
  );
  if problem is not null then
    raise exception 'ABORTED, nothing changed: anon/authenticated belong to roles with access: %', problem;
  end if;

  -- 4. No view over the tables that anon / authenticated can use (a view owned by the table
  --    owner reads past both the grants and RLS).
  select string_agg(distinct v.oid::regclass::text, ', ') into problem
  from pg_depend d
  join pg_rewrite rw on rw.oid = d.objid
  join pg_class v on v.oid = rw.ev_class
  where d.refobjid = any (tables::regclass[])
    and v.oid <> d.refobjid
    and (has_table_privilege('anon', v.oid, 'SELECT,INSERT,UPDATE,DELETE')
         or has_table_privilege('authenticated', v.oid, 'SELECT,INSERT,UPDATE,DELETE'));
  if problem is not null then
    raise exception 'ABORTED, nothing changed: views reachable by anon/authenticated: %', problem;
  end if;

  -- 5. No SECURITY DEFINER function naming the tables that anon / authenticated can call
  --    (it would run as its owner, past the grants and RLS).
  select string_agg(pr.oid::regprocedure::text, ', ') into problem
  from pg_proc pr
  join pg_namespace n on n.oid = pr.pronamespace
  where n.nspname not in ('pg_catalog', 'information_schema')
    and pr.prosecdef
    and pr.prosrc ~* 'baseball_shared_(draft_rooms|leagues)'
    and (has_function_privilege('anon', pr.oid, 'EXECUTE')
         or has_function_privilege('authenticated', pr.oid, 'EXECUTE'));
  if problem is not null then
    raise exception 'ABORTED, nothing changed: security definer functions callable by anon/authenticated: %', problem;
  end if;

  -- 6. These tables have text keys and no sequence. If one ever gains a serial / identity column,
  --    its sequence privileges need revoking too, so refuse rather than leave one open.
  select string_agg(c.relname || '.' || a.attname, ', ') into problem
  from pg_attribute a
  join pg_class c on c.oid = a.attrelid
  where c.oid = any (tables::regclass[]) and a.attnum > 0 and not a.attisdropped
    and pg_get_serial_sequence('public.' || c.relname, a.attname) is not null;
  if problem is not null then
    raise exception 'ABORTED, nothing changed: serial/identity columns need a sequence revoke added: %', problem;
  end if;

  -- Snapshot of every service_role grant on the suite and baseball-shared tables, compared afterwards.
  select coalesce(string_agg(c.relname || ':' || a.privilege_type, ',' order by c.relname, a.privilege_type), '')
    into service_role_before
  from pg_class c
  cross join lateral aclexplode(c.relacl) a
  where c.relnamespace = 'public'::regnamespace
    and (c.relname like 'suite\_%' or c.relname like 'baseball\_shared\_%')
    and a.grantee = 'service_role'::regrole;

  ----------------------------------------------------------------------------
  -- The change
  ----------------------------------------------------------------------------
  alter table public.baseball_shared_draft_rooms enable row level security;
  alter table public.baseball_shared_leagues enable row level security;

  revoke all on table public.baseball_shared_draft_rooms, public.baseball_shared_leagues
    from anon, authenticated;

  ----------------------------------------------------------------------------
  -- Proof after the change (any failure here undoes the change above)
  ----------------------------------------------------------------------------
  if exists (select 1 from pg_class where oid = any (tables::regclass[]) and not relrowsecurity) then
    raise exception 'ABORTED, nothing changed: RLS did not turn on';
  end if;
  foreach r in array api_roles loop
    foreach t in array tables loop
      foreach p in array array['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] loop
        if has_table_privilege(r, t, p) then
          raise exception 'ABORTED, nothing changed: % still has % on %', r, p, t;
        end if;
      end loop;
      foreach p in array array['SELECT', 'INSERT', 'UPDATE', 'REFERENCES'] loop
        if has_any_column_privilege(r, t, p) then
          raise exception 'ABORTED, nothing changed: % still has column % on %', r, p, t;
        end if;
      end loop;
    end loop;
  end loop;

  select coalesce(string_agg(c.relname || ':' || a.privilege_type, ',' order by c.relname, a.privilege_type), '')
    into service_role_after
  from pg_class c
  cross join lateral aclexplode(c.relacl) a
  where c.relnamespace = 'public'::regnamespace
    and (c.relname like 'suite\_%' or c.relname like 'baseball\_shared\_%')
    and a.grantee = 'service_role'::regrole;
  if service_role_after is distinct from service_role_before then
    raise exception 'ABORTED, nothing changed: service_role grants would change';
  end if;

  raise notice 'Step B applied: RLS on and anon/authenticated access removed for baseball_shared_draft_rooms and baseball_shared_leagues; service_role grants unchanged.';
end
$containment$;
