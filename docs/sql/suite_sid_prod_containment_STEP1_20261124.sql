-- STEP 1 of the suite_sid containment — PRODUCTION, 2026-11-24. DO NOT RUN without the owner's explicit approval.
-- One DO block = one transaction. Every check that fails raises, and then NOTHING below has happened.
--
--   1a. lock (writes to suite_saved_items wait; 5 s lock timeout), then checks: right project (3 Auth users), 1485 browser-session rows (+25), ~1308 other saved items
--   1b. evidence: copies NON-SENSITIVE metadata of every browser-session row into
--       security_audit.suite_sid_bridge_snapshot_20261124 (no token, no sid: the sid is stored only as a SHA-256)
--   1c. trigger: public.suite_block_browser_session_bridge — from now on any write of a browser-session row,
--       by any app, stores valid = false and no token (the write still succeeds, so sign-in keeps working)
--   1d. self-test of the trigger on a throw-away row, which is then deleted
--   1e. revocation: every browser-session row -> valid = false, tokens erased (rows kept for the audit trail)
--   1f. verification: no row valid or holding a token, other saved items byte-for-byte unchanged,
--       snapshot complete, trigger enabled, Auth users unchanged
-- Never touches: other saved items, users, Auth, recordings, compositions, leagues, drafts, strategies,
-- subscriptions, billing.
-- Undo of 1c only (if ever needed): drop trigger suite_block_browser_session_bridge on public.suite_saved_items;
--                                    drop function public.suite_block_browser_session_bridge();

do $$
declare
  expected_rows       constant int := 1485;
  allowed_new_rows    constant int := 25;
  expected_other      constant int := 1308;
  allowed_other_drift constant int := 100;
  expected_auth_users constant int := 3;
  n_users int; n_scope int; n_valid int; n_other int; n_snap int; n_updated int; n_left int;
  fp_before text; fp_after text; probe_key text; probe_insert_ok boolean; probe_update_ok boolean;
begin
  -- 1a. lock first, so the counts, the fingerprint, the snapshot and the revocation all see the same data.
  --     SHARE ROW EXCLUSIVE blocks writes to suite_saved_items (not reads) until this transaction ends;
  --     it is the same lock CREATE TRIGGER takes. Give up after 5 s instead of queueing behind another writer.
  perform set_config('lock_timeout', '5s', true);
  lock table public.suite_saved_items in share row exclusive mode;

  -- checks
  select count(*) into n_users from auth.users;
  if n_users <> expected_auth_users then
    raise exception 'refused: % Auth users, expected % (wrong project?)', n_users, expected_auth_users;
  end if;
  select count(*), count(*) filter (where valid) into n_scope, n_valid
    from public.suite_saved_items where app = '_auth_browser' and item_type = 'browser_session';
  if n_scope < expected_rows or n_scope > expected_rows + allowed_new_rows then
    raise exception 'refused: % browser-session rows, expected % (+ up to % new)', n_scope, expected_rows, allowed_new_rows;
  end if;
  select count(*) into n_other
    from public.suite_saved_items where not (app = '_auth_browser' and item_type = 'browser_session');
  if abs(n_other - expected_other) > allowed_other_drift then
    raise exception 'refused: % other saved items, expected about %', n_other, expected_other;
  end if;
  if to_regclass('security_audit.suite_sid_bridge_snapshot_20261124') is not null then
    raise exception 'refused: the evidence snapshot already exists (step 1 has run before?)';
  end if;
  select md5(coalesce(string_agg(md5(x::text), ',' order by x.id), '')) into fp_before
    from public.suite_saved_items x where not (x.app = '_auth_browser' and x.item_type = 'browser_session');

  -- 1b. evidence snapshot (private schema, not reachable through the API)
  execute 'create schema if not exists security_audit';
  execute 'revoke all on schema security_audit from public, anon, authenticated';
  execute $fn$
    create function pg_temp.suite_jwt_claims(tok text) returns jsonb language plpgsql as $body$
    declare part text := split_part(coalesce(tok, ''), '.', 2);
    begin
      if part = '' or part !~ '^[A-Za-z0-9_-]+$' then return null; end if;
      return convert_from(decode(rpad(translate(part, '-_', '+/'), ((length(part) + 3) / 4) * 4, '='), 'base64'), 'UTF8')::jsonb;
    exception when others then
      return null;
    end $body$
  $fn$;
  execute $sql$
    create table security_audit.suite_sid_bridge_snapshot_20261124 as
    select i.id                                                        as saved_item_id,
           i.user_id                                                   as profile_id,
           encode(sha256(convert_to(i.item_key, 'UTF8')), 'hex')       as sid_sha256,
           i.valid                                                     as valid_before,
           i.updated_at                                                as updated_at_before,
           i.payload ? 'access_token'                                  as had_access_token,
           i.payload ? 'refresh_token'                                 as had_refresh_token,
           c ->> 'sub'                                                 as token_auth_user_id,
           c ->> 'session_id'                                          as token_session_id,
           to_timestamp(nullif(c ->> 'iat', '')::double precision)     as token_issued_at,
           to_timestamp(nullif(c ->> 'exp', '')::double precision)     as token_expires_at,
           c ->> 'aal'                                                 as token_aal,
           now()                                                       as snapshot_at
    from public.suite_saved_items i
    cross join lateral (select pg_temp.suite_jwt_claims(i.payload ->> 'access_token') as c) j
    where i.app = '_auth_browser' and i.item_type = 'browser_session'
  $sql$;
  execute 'revoke all on security_audit.suite_sid_bridge_snapshot_20261124 from public, anon, authenticated';
  execute 'alter table security_audit.suite_sid_bridge_snapshot_20261124 enable row level security';
  select count(*) into n_snap from security_audit.suite_sid_bridge_snapshot_20261124;
  if n_snap <> n_scope then
    raise exception 'rolled back: snapshot holds % rows, scope is %', n_snap, n_scope;
  end if;

  -- 1c. blocking trigger
  execute $fn$
    create or replace function public.suite_block_browser_session_bridge()
    returns trigger language plpgsql set search_path = pg_catalog as $body$
    begin
      if new.app = '_auth_browser' and new.item_type = 'browser_session' then
        new.valid   := false;
        new.payload := jsonb_build_object('revoked', true, 'revoked_reason', 'suite_sid_disabled_20261123');
      end if;
      return new;
    end $body$
  $fn$;
  execute 'drop trigger if exists suite_block_browser_session_bridge on public.suite_saved_items';
  execute 'create trigger suite_block_browser_session_bridge before insert or update on public.suite_saved_items '
       || 'for each row execute function public.suite_block_browser_session_bridge()';

  -- 1d. self-tests, checked separately: (i) an INSERT that tries to store tokens, (ii) an UPDATE that tries to
  --     put tokens back and re-validate. Both must end up valid = false with no token. The probe row is deleted.
  probe_key := 'trigger-selftest-' || gen_random_uuid()::text;
  insert into public.suite_saved_items (user_id, app, item_type, item_key, title, payload, valid)
  select user_id, app, item_type, probe_key, title, '{"access_token": "selftest", "refresh_token": "selftest"}'::jsonb, true
    from public.suite_saved_items where app = '_auth_browser' and item_type = 'browser_session' limit 1;
  select count(*) = 1 and bool_and(not valid and not (payload ? 'access_token') and not (payload ? 'refresh_token'))
    into probe_insert_ok
    from public.suite_saved_items where item_key = probe_key and app = '_auth_browser' and item_type = 'browser_session';
  if probe_insert_ok is not true then
    raise exception 'rolled back: trigger INSERT self-test failed';
  end if;
  update public.suite_saved_items set payload = '{"access_token": "selftest2", "refresh_token": "selftest2"}'::jsonb, valid = true
   where item_key = probe_key and app = '_auth_browser' and item_type = 'browser_session';
  select count(*) = 1 and bool_and(not valid and not (payload ? 'access_token') and not (payload ? 'refresh_token'))
    into probe_update_ok
    from public.suite_saved_items where item_key = probe_key and app = '_auth_browser' and item_type = 'browser_session';
  if probe_update_ok is not true then
    raise exception 'rolled back: trigger UPDATE self-test failed';
  end if;
  delete from public.suite_saved_items where item_key = probe_key and app = '_auth_browser' and item_type = 'browser_session';

  -- 1e. revocation
  update public.suite_saved_items
     set valid = false,
         payload = jsonb_build_object('revoked', true, 'revoked_reason', 'suite_sid_disabled_20261123'),
         updated_at = now()
   where app = '_auth_browser' and item_type = 'browser_session';
  get diagnostics n_updated = row_count;

  -- 1f. verification
  if n_updated <> n_scope then
    raise exception 'rolled back: updated % rows, scope was %', n_updated, n_scope;
  end if;
  select count(*) into n_left from public.suite_saved_items
   where app = '_auth_browser' and item_type = 'browser_session'
     and (valid or payload ? 'access_token' or payload ? 'refresh_token');
  if n_left <> 0 then
    raise exception 'rolled back: % browser-session rows still valid or holding a token', n_left;
  end if;
  select md5(coalesce(string_agg(md5(x::text), ',' order by x.id), '')) into fp_after
    from public.suite_saved_items x where not (x.app = '_auth_browser' and x.item_type = 'browser_session');
  if fp_after is distinct from fp_before then
    raise exception 'rolled back: other saved items changed';
  end if;
  if not exists (select 1 from pg_trigger where tgname = 'suite_block_browser_session_bridge'
                   and tgrelid = 'public.suite_saved_items'::regclass and tgenabled = 'O') then
    raise exception 'rolled back: trigger missing or disabled';
  end if;
  if (select count(*) from auth.users) <> n_users then
    raise exception 'rolled back: Auth users changed';
  end if;

  raise notice 'OK: evidence snapshot % rows; trigger installed, INSERT and UPDATE self-tests passed; revoked % browser-session rows (% had been valid); % other saved items unchanged',
    n_snap, n_updated, n_valid, n_other;
end $$;

-- Verify afterwards (read-only). Expected: 1485 | 0 | 0 | 1308 | 1485 | true
select count(*) as total,
       count(*) filter (where valid) as valid_rows,
       count(*) filter (where payload ? 'refresh_token' or payload ? 'access_token') as rows_holding_tokens,
       (select count(*) from public.suite_saved_items where not (app = '_auth_browser' and item_type = 'browser_session')) as other_saved_items,
       (select count(*) from security_audit.suite_sid_bridge_snapshot_20261124) as evidence_rows,
       exists (select 1 from pg_trigger where tgname = 'suite_block_browser_session_bridge' and tgenabled = 'O') as trigger_on
from public.suite_saved_items
where app = '_auth_browser' and item_type = 'browser_session';
