-- GUARDED REVOCATION of legacy browser-session (suite_sid) records — PRODUCTION, 2026-11-24.
-- DO NOT RUN without the owner's explicit approval of this operation.
-- One DO block = one transaction: if any check fails it raises, and NOTHING is changed.
--
-- Changes: only public.suite_saved_items rows with app = '_auth_browser' AND item_type = 'browser_session'.
--   valid -> false; payload (access + refresh token) -> {"revoked": true, "revoked_reason": ...}; updated_at -> now().
--   The rows themselves are kept (audit trail: owner, key, dates).
-- Never changes: the other saved items, users, accounts, recordings, compositions, leagues, drafts,
--   strategies, subscriptions, billing, Auth. It touches no other table.
-- Pinned from the 2026-11-24 preflight: 1485 browser-session rows, 1308 other saved items, 3 Auth users.

do $$
declare
  expected_rows       constant int := 1485;  -- preflight: browser_session rows
  allowed_new_rows    constant int := 25;    -- rows an unpatched app might add before this runs
  expected_other      constant int := 1308;  -- preflight: other saved items
  allowed_other_drift constant int := 100;   -- normal saving between the preflight and this run
  expected_auth_users constant int := 3;     -- preflight: all Auth users (right-project check)
  n_scope int; n_valid int; n_updated int; n_left int; n_other int; n_users int;
  other_fp_before text; other_fp_after text;
begin
  -- 1. right project, expected scope
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

  -- 2. fingerprint every other saved item (content, not just the count)
  select md5(coalesce(string_agg(md5(x::text), ',' order by x.id), '')) into other_fp_before
    from public.suite_saved_items x where not (x.app = '_auth_browser' and x.item_type = 'browser_session');

  -- 3. the change
  update public.suite_saved_items
     set valid      = false,
         payload    = jsonb_build_object('revoked', true, 'revoked_reason', 'suite_sid_disabled_20261123'),
         updated_at = now()
   where app = '_auth_browser' and item_type = 'browser_session';
  get diagnostics n_updated = row_count;

  -- 4. verification — any failure rolls the update back
  if n_updated <> n_scope then
    raise exception 'rolled back: updated % rows, scope was %', n_updated, n_scope;
  end if;
  select count(*) into n_left
    from public.suite_saved_items
   where app = '_auth_browser' and item_type = 'browser_session'
     and (valid or payload ? 'access_token' or payload ? 'refresh_token');
  if n_left <> 0 then
    raise exception 'rolled back: % browser-session rows still valid or holding a token', n_left;
  end if;
  select md5(coalesce(string_agg(md5(x::text), ',' order by x.id), '')) into other_fp_after
    from public.suite_saved_items x where not (x.app = '_auth_browser' and x.item_type = 'browser_session');
  if other_fp_after is distinct from other_fp_before then
    raise exception 'rolled back: other saved items changed';
  end if;
  if (select count(*) from auth.users) <> n_users then
    raise exception 'rolled back: Auth users changed';
  end if;

  raise notice 'OK: revoked % browser-session rows (% had been valid); % other saved items unchanged (content fingerprint identical)',
    n_updated, n_valid, n_other;
end $$;

-- Verify afterwards (read-only). Expected: total 1485 (or a few more), valid_rows 0, rows_holding_tokens 0.
select count(*) as total,
       count(*) filter (where valid) as valid_rows,
       count(*) filter (where payload ? 'refresh_token' or payload ? 'access_token') as rows_holding_tokens,
       (select count(*) from public.suite_saved_items where not (app = '_auth_browser' and item_type = 'browser_session')) as other_saved_items
from public.suite_saved_items
where app = '_auth_browser' and item_type = 'browser_session';
