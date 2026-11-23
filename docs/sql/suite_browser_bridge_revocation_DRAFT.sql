-- DRAFT — requires the owner's explicit approval before it is run against PRODUCTION.
-- Revokes every stored browser sign-in record behind a `suite_sid` URL (security hotfix 2026-11-23).
--
-- Scope: ONLY rows of public.suite_saved_items with app = '_auth_browser' AND item_type =
-- 'browser_session'. No saved draft, strategy, league, workspace, setting, subscription or user row is
-- touched. Each matched row is kept (for the audit trail), marked valid = false, and its stored tokens
-- are replaced by {"revoked": true}, so no copied URL can restore a sign-in from it in any Suite app.
--
-- Effect on users: a page reload in an app that still uses `suite_sid` (the sibling apps until they are
-- patched) asks them to sign in again. Open, signed-in tabs keep working. Nothing else changes.
-- Rollback: none needed and none possible for the token values (they are erased by design); a user
-- simply signs in again.
--
-- Run each block separately in the Supabase SQL editor of the production project.

-- R0. Preflight (read-only, aggregate only: no token, id or email is returned).
select count(*)                                                  as browser_session_rows,
       count(*) filter (where valid)                             as valid_rows,
       count(*) filter (where payload ? 'refresh_token')         as rows_holding_refresh_token,
       count(distinct user_id)                                   as accounts,
       min(updated_at)                                           as oldest,
       max(updated_at)                                           as newest
from public.suite_saved_items
where app = '_auth_browser' and item_type = 'browser_session';

-- R1. Revoke (one transaction). Expect "UPDATE <browser_session_rows from R0>".
begin;
update public.suite_saved_items
   set valid      = false,
       payload    = jsonb_build_object('revoked', true, 'revoked_reason', 'suite_sid_disabled_20261123'),
       updated_at = now()
 where app = '_auth_browser'
   and item_type = 'browser_session';
-- Must return 0 before COMMIT; if not, ROLLBACK and stop.
select count(*) as rows_still_holding_tokens
from public.suite_saved_items
where app = '_auth_browser' and item_type = 'browser_session'
  and (valid or payload ? 'access_token' or payload ? 'refresh_token');
commit;

-- R2. Verify (read-only). Expect valid_rows = 0 and rows_holding_refresh_token = 0. Rows written after R1
-- come from apps that still use `suite_sid`; re-run R1 after those apps are patched.
select count(*) filter (where valid)                     as valid_rows,
       count(*) filter (where payload ? 'refresh_token') as rows_holding_refresh_token,
       max(updated_at)                                   as newest
from public.suite_saved_items
where app = '_auth_browser' and item_type = 'browser_session';

-- OPTIONAL A1 (separate approval). End the Supabase Auth sessions of the accounts that had a stored
-- browser sign-in record, so any session ever restored through a copied URL stops working at its next
-- token refresh. Impact: those accounts are signed out of EVERY app on this Supabase project, including
-- the production app, and sign in again. Count first:
select count(distinct s.user_id) as accounts, count(*) as auth_sessions
from auth.sessions s
where s.user_id in (
  -- bridge rows carry either the suite_users id (linked to Auth by email) or the Auth user id itself
  select a.id
  from public.suite_saved_items i
  left join public.suite_users u on u.id = i.user_id
  join auth.users a on a.id = i.user_id or (u.email <> '' and lower(a.email) = lower(u.email))
  where i.app = '_auth_browser' and i.item_type = 'browser_session'
);
-- The delete itself (auth.sessions for exactly those accounts) is prepared only after this count is
-- reviewed and the owner approves A1.
