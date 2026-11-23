-- DRAFT — requires the owner's approval before it is applied to PRODUCTION.
-- Stops ANY app (patched or not) from storing sign-in tokens in a browser-session record, so a copied
-- suite_sid URL can never restore a session in any Suite app, even before that app is patched.
--
-- How: a BEFORE INSERT OR UPDATE trigger on public.suite_saved_items. For rows with app = '_auth_browser'
-- and item_type = 'browser_session' it forces valid = false and replaces the payload with
-- {"revoked": true}. Every other row passes through unchanged. The write itself still succeeds, so an
-- unpatched app's sign-in is not interrupted: its save "works", but nothing usable is stored, and a page
-- reload asks the user to sign in again (the same behaviour as the patched Baseball Dev).
--
-- Checked before proposing (2026-11-23): none of the unpatched apps (Music, Investment, Command Center,
-- AMI, NBA, Future Lens, dev and main) refuses a sign-in when this save stores nothing — their save
-- result is ignored. Baseball Dev no longer writes these records at all.
--
-- Rollback: drop trigger suite_block_browser_session_bridge on public.suite_saved_items;
--           drop function public.suite_block_browser_session_bridge();

create or replace function public.suite_block_browser_session_bridge()
returns trigger
language plpgsql
as $$
begin
  if new.app = '_auth_browser' and new.item_type = 'browser_session' then
    new.valid   := false;
    new.payload := jsonb_build_object('revoked', true, 'revoked_reason', 'bridge_disabled_trigger_20261123');
  end if;
  return new;
end;
$$;

drop trigger if exists suite_block_browser_session_bridge on public.suite_saved_items;
create trigger suite_block_browser_session_bridge
  before insert or update on public.suite_saved_items
  for each row execute function public.suite_block_browser_session_bridge();

-- Verify (read-only): the trigger exists and no browser-session row holds a token.
select tgname, tgenabled from pg_trigger where tgname = 'suite_block_browser_session_bridge';
select count(*) filter (where valid) as valid_rows,
       count(*) filter (where payload ? 'refresh_token' or payload ? 'access_token') as rows_holding_tokens
from public.suite_saved_items where app = '_auth_browser' and item_type = 'browser_session';
