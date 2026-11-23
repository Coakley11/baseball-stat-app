-- GUARDED revocation — DO NOT RUN until the owner approves it after reviewing the preflight
-- (suite_sid_prod_preflight_READONLY.sql). Runs in one transaction and ROLLS BACK BY ITSELF if any check fails.
--
-- Scope: only public.suite_saved_items rows with app = '_auth_browser' AND item_type = 'browser_session'.
-- Each row is kept for the audit trail, marked valid = false, and its tokens replaced by {"revoked": true}.
-- No draft, strategy, league, workspace, setting, subscription or user row is touched.
--
-- Before running: replace 0 on the EXPECTED_ROWS line with "browser_session rows" from the preflight.
-- The block refuses to run if EXPECTED_ROWS is still 0, and refuses if the live count differs from it by
-- more than ALLOWED_NEW_ROWS (rows written by still-unpatched apps between the preflight and this run).

begin;

do $$
declare
  expected_rows    constant int := 0;    -- EXPECTED_ROWS: set from the preflight
  allowed_new_rows constant int := 25;   -- ALLOWED_NEW_ROWS
  n_scope int; n_updated int; n_left int; other_before bigint; other_after bigint;
begin
  if expected_rows <= 0 then
    raise exception 'refused: set expected_rows from the preflight first';
  end if;
  select count(*) into n_scope from public.suite_saved_items
   where app = '_auth_browser' and item_type = 'browser_session';
  if n_scope < expected_rows or n_scope > expected_rows + allowed_new_rows then
    raise exception 'refused: % rows in scope, expected % (+% allowed)', n_scope, expected_rows, allowed_new_rows;
  end if;
  select count(*) into other_before from public.suite_saved_items
   where not (app = '_auth_browser' and item_type = 'browser_session');

  update public.suite_saved_items
     set valid      = false,
         payload    = jsonb_build_object('revoked', true, 'revoked_reason', 'suite_sid_disabled_20261123'),
         updated_at = now()
   where app = '_auth_browser' and item_type = 'browser_session';
  get diagnostics n_updated = row_count;

  select count(*) into n_left from public.suite_saved_items
   where app = '_auth_browser' and item_type = 'browser_session'
     and (valid or payload ? 'access_token' or payload ? 'refresh_token');
  select count(*) into other_after from public.suite_saved_items
   where not (app = '_auth_browser' and item_type = 'browser_session');

  if n_updated <> n_scope then
    raise exception 'rolled back: updated % rows, scope was %', n_updated, n_scope;
  end if;
  if n_left <> 0 then
    raise exception 'rolled back: % rows still valid or holding tokens', n_left;
  end if;
  if other_after <> other_before then
    raise exception 'rolled back: other saved items changed (% -> %)', other_before, other_after;
  end if;
  raise notice 'OK: revoked % browser-session rows; % other saved items unchanged', n_updated, other_after;
end $$;

commit;   -- after a raised exception the transaction is aborted and this COMMIT performs a ROLLBACK

-- Verify afterwards (read-only): expect 0 and 0.
select count(*) filter (where valid) as valid_rows,
       count(*) filter (where payload ? 'refresh_token' or payload ? 'access_token') as rows_holding_tokens
from public.suite_saved_items
where app = '_auth_browser' and item_type = 'browser_session';
