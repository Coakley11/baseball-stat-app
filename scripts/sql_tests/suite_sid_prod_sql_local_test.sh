#!/usr/bin/env bash
# Tests the suite_sid production SQL (preflight, guarded revocation, bridge-block trigger) against a throwaway
# local PostgreSQL cluster built from suite_rls_fixture.sql plus Supabase-like auth tables. Fake data only;
# never touches a real project.
#
#   scripts/sql_tests/suite_sid_prod_sql_local_test.sh <empty scratch dir> [pg bin dir] [port]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SQL="$HERE/../../docs/sql"
PRE="$SQL/suite_sid_prod_preflight_READONLY.sql"
REV="$SQL/suite_sid_prod_revocation_GUARDED.sql"
TRG="$SQL/suite_sid_bridge_block_trigger_DRAFT.sql"
WORK="${1:?usage: $0 <scratch dir> [pg bin dir] [port]}"
PGBIN="${2:-/c/Program Files/PostgreSQL/17/bin}"
PORT="${3:-55433}"
DATA="$WORK/pgdata"; DB=suite; PASS=0; FAIL=0
pg() { "$PGBIN/psql" -X -q -tA -v ON_ERROR_STOP=1 -h localhost -p "$PORT" -U postgres -d "$DB" "$@"; }
ok()  { PASS=$((PASS + 1)); echo "  ok    $1"; }
bad() { FAIL=$((FAIL + 1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && echo "        $2"; }
equals() { if [ "$1" = "$2" ]; then ok "$3"; else bad "$3" "expected [$2] got [$1]"; fi; }
q() { pg -c "$1" 2>&1; }
fp_other() { q "select md5(coalesce(string_agg(md5(x::text), ',' order by x.id), '')) from public.suite_saved_items x where not (app = '_auth_browser' and item_type = 'browser_session')"; }
fp_all()   { q "select md5(coalesce(string_agg(md5(x::text), ',' order by x.id), '')) from public.suite_saved_items x"; }
bridge()   { q "select count(*) filter (where valid) || '/' || count(*) filter (where payload ? 'refresh_token' or payload ? 'access_token') || '/' || count(*) from public.suite_saved_items where app = '_auth_browser' and item_type = 'browser_session'"; }
rev_with() { sed "s/expected_rows    constant int := 0;/expected_rows    constant int := $1;/" "$REV" > "$WORK/rev.sql"; pg -f "$WORK/rev.sql" > "$WORK/rev_out.txt" 2>&1; }
pre_val()  { pg -f "$PRE" | grep -F "|$1|" | head -1 | awk -F'|' '{print $3}'; }

[ -e "$DATA" ] && { echo "refusing: $DATA already exists"; exit 2; }
mkdir -p "$WORK"
"$PGBIN/initdb" -D "$DATA" -U postgres -A trust -E UTF8 --no-locale >/dev/null || exit 2
"$PGBIN/pg_ctl" -D "$DATA" -l "$WORK/pg.log" -o "-p $PORT -c listen_addresses=localhost" -w start >/dev/null || exit 2
trap '"$PGBIN/pg_ctl" -D "$DATA" -m fast -w stop >/dev/null' EXIT
"$PGBIN/createdb" -h localhost -p "$PORT" -U postgres "$DB" || exit 2
pg -f "$HERE/suite_rls_fixture.sql" >/dev/null || exit 2
pg >/dev/null <<'SQL'
create schema auth;
create table auth.users (id uuid primary key, email text);
create table auth.sessions (id uuid primary key, user_id uuid references auth.users (id), not_after timestamptz);
create table auth.refresh_tokens (id bigserial primary key, session_id uuid references auth.sessions (id), revoked boolean default false);
insert into auth.users values ('00000000-0000-0000-0000-0000000000a1', 'a@example.invalid'),
                              ('00000000-0000-0000-0000-0000000000b1', 'b@example.invalid'),
                              ('00000000-0000-0000-0000-0000000000c1', 'c@example.invalid');
insert into auth.sessions values ('00000000-0000-0000-0000-00000000a001', '00000000-0000-0000-0000-0000000000a1', null),
                                 ('00000000-0000-0000-0000-00000000a002', '00000000-0000-0000-0000-0000000000a1', now() - interval '1 day'),
                                 ('00000000-0000-0000-0000-00000000c001', '00000000-0000-0000-0000-0000000000c1', null);
insert into auth.refresh_tokens (session_id, revoked) values ('00000000-0000-0000-0000-00000000a001', false),
                                                             ('00000000-0000-0000-0000-00000000a002', true);
-- more bridge rows: B valid with tokens, A an older invalidated row that still holds tokens
insert into public.suite_saved_items (user_id, app, item_type, item_key, title, payload, valid) values
  ('00000000-0000-0000-0000-00000000000b', '_auth_browser', 'browser_session', 'sid-b', 'session',
   '{"access_token": "fake-access-b", "refresh_token": "fake-refresh-b"}', true),
  ('00000000-0000-0000-0000-00000000000a', '_auth_browser', 'browser_session', 'sid-a-old', 'session',
   '{"access_token": "fake-access-a0", "refresh_token": "fake-refresh-a0"}', false);
SQL

echo "Preflight (read-only)"
if PGOPTIONS="-c default_transaction_read_only=on" pg -f "$PRE" > "$WORK/pre.txt" 2>&1; then ok "runs inside a read-only transaction"; else bad "runs read-only" "$(cat "$WORK/pre.txt")"; fi
grep -qiE "fake-(access|refresh)|@example" "$WORK/pre.txt" && bad "returns no token or email" || ok "returns no token or email"
equals "$(pre_val 'browser_session rows')" "3" "counts browser_session rows"
equals "$(pre_val 'valid rows holding a refresh token')" "2" "counts valid rows holding a refresh token"
equals "$(pre_val 'distinct row owners (user_id)')" "2" "counts distinct owners"
equals "$(pre_val 'Auth accounts linked to bridge rows')" "2" "links bridge rows to Auth accounts by email"
equals "$(pre_val 'their Auth sessions')" "2" "counts those accounts' Auth sessions (not C's)"
equals "$(pre_val 'their Auth sessions not expired')" "1" "counts unexpired sessions"
equals "$(pre_val 'their unrevoked refresh tokens')" "1" "counts unrevoked refresh tokens"
grep -q "3 access suite_saved_items|anon privileges" "$WORK/pre.txt" && ok "reports anon access per table" || bad "reports anon access per table" "$(grep 'access' "$WORK/pre.txt" | head -3)"

echo "Guarded revocation refuses and changes nothing"
before=$(fp_all)
rev_with 0; grep -q "set expected_rows" "$WORK/rev_out.txt" && ok "refuses while EXPECTED_ROWS is unset" || bad "refuses while unset" "$(cat "$WORK/rev_out.txt")"
equals "$(fp_all)" "$before" "  nothing changed"
rev_with 99; grep -q "rows in scope, expected 99" "$WORK/rev_out.txt" && ok "refuses when the live count differs from the preflight" || bad "refuses on count mismatch" "$(cat "$WORK/rev_out.txt")"
equals "$(fp_all)" "$before" "  nothing changed"
# a check failing AFTER the update must roll the update back
q "create function public._qa_keep_tokens() returns trigger language plpgsql as \$\$ begin new.payload := new.payload || '{\"refresh_token\":\"x\"}'; return new; end \$\$; create trigger _qa_keep_tokens before update on public.suite_saved_items for each row execute function public._qa_keep_tokens();" >/dev/null
rev_with 3; grep -q "rolled back: .* still valid or holding tokens" "$WORK/rev_out.txt" && ok "rolls back when tokens survive the update" || bad "rolls back on failed verification" "$(cat "$WORK/rev_out.txt")"
equals "$(fp_all)" "$before" "  nothing changed (update rolled back)"
q "drop trigger _qa_keep_tokens on public.suite_saved_items; drop function public._qa_keep_tokens();" >/dev/null

echo "Guarded revocation applies with the right count"
other=$(fp_other)
rev_with 3; grep -q "OK: revoked 3 browser-session rows" "$WORK/rev_out.txt" && ok "revokes exactly the 3 rows" || bad "revokes" "$(cat "$WORK/rev_out.txt")"
equals "$(bridge)" "0/0/3" "bridge rows: 0 valid, 0 holding tokens, 3 kept"
equals "$(fp_other)" "$other" "every other saved item is byte-identical"
equals "$(q "select count(*) from public.suite_user_settings")" "2" "settings untouched"

echo "Bridge-block trigger"
pg -f "$TRG" > "$WORK/trg.txt" 2>&1 && ok "applies" || bad "applies" "$(cat "$WORK/trg.txt")"
q "insert into public.suite_saved_items (user_id, app, item_type, item_key, title, payload, valid) values ('00000000-0000-0000-0000-00000000000a', '_auth_browser', 'browser_session', 'sid-new', 's', '{\"access_token\":\"t\",\"refresh_token\":\"r\"}', true) on conflict (user_id, app, item_type, item_key) do update set payload = excluded.payload, valid = true" >/dev/null
equals "$(q "select valid::text || ' ' || (payload ? 'refresh_token')::text from public.suite_saved_items where item_key = 'sid-new'")" "false false" "an unpatched app's new record stores no token"
q "update public.suite_saved_items set valid = true, payload = '{\"access_token\":\"t\",\"refresh_token\":\"r\"}' where item_key = 'sid-b'" >/dev/null
equals "$(q "select valid::text || ' ' || (payload ? 'refresh_token')::text from public.suite_saved_items where item_key = 'sid-b'")" "false false" "an unpatched app's update stores no token"
q "insert into public.suite_saved_items (user_id, app, item_type, item_key, title, payload) values ('00000000-0000-0000-0000-00000000000b', 'music', 'practice', 'p1', 'P', '{\"refresh_token\":\"not-a-bridge-row\"}')" >/dev/null
equals "$(q "select valid::text || ' ' || (payload->>'refresh_token') from public.suite_saved_items where item_key = 'p1'")" "true not-a-bridge-row" "other apps' rows pass through unchanged"
q "drop trigger suite_block_browser_session_bridge on public.suite_saved_items; drop function public.suite_block_browser_session_bridge();" >/dev/null && ok "rollback statements work" || bad "rollback statements"

echo; echo "PASS $PASS  FAIL $FAIL"
[ "$FAIL" -eq 0 ]
