#!/usr/bin/env bash
# Tests suite_sid_prod_containment_STEP1_20261124.sql (evidence snapshot + blocking trigger + revocation, one
# transaction) on a throwaway local cluster (suite_rls_fixture.sql + Supabase-like auth tables). Fake data only.
#   scripts/sql_tests/suite_sid_containment_step1_local_test.sh <empty scratch dir> [pg bin dir] [port]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
STEP1="$HERE/../../docs/sql/suite_sid_prod_containment_STEP1_20261124.sql"
WORK="${1:?usage: $0 <scratch dir> [pg bin dir] [port]}"
PGBIN="${2:-/c/Program Files/PostgreSQL/17/bin}"
PORT="${3:-55445}"
DATA="$WORK/pgdata"; DB=suite; PASS=0; FAIL=0
pg() { "$PGBIN/psql" -X -q -tA -v ON_ERROR_STOP=1 -h localhost -p "$PORT" -U postgres -d "$DB" "$@"; }
ok()  { PASS=$((PASS + 1)); echo "  ok    $1"; }
bad() { FAIL=$((FAIL + 1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && echo "        $2"; }
equals() { if [ "$1" = "$2" ]; then ok "$3"; else bad "$3" "expected [$2] got [$1]"; fi; }
q() { pg -c "$1" 2>&1; }
fp_all() { q "select md5(coalesce(string_agg(md5(x::text), ',' order by x.id), '')) from public.suite_saved_items x"; }
fp_other() { q "select md5(coalesce(string_agg(md5(x::text), ',' order by x.id), '')) from public.suite_saved_items x where not (app = '_auth_browser' and item_type = 'browser_session')"; }
schema_state() { q "select count(*) from pg_namespace where nspname = 'security_audit'"; }
trig_state() { q "select count(*) from pg_trigger where tgname = 'suite_block_browser_session_bridge'"; }
run_with() {  # bridge-rows other-items auth-users
  sed -e "s/expected_rows       constant int := 1485;/expected_rows       constant int := $1;/" \
      -e "s/expected_other      constant int := 1308;/expected_other      constant int := $2;/" \
      -e "s/expected_auth_users constant int := 3;/expected_auth_users constant int := $3;/" "$STEP1" > "$WORK/step1.sql"
  pg -f "$WORK/step1.sql" > "$WORK/out.txt" 2>&1
}
jwt() { echo "eyJhbGciOiJIUzI1NiJ9.$(printf '%s' "$1" | base64 -w0 | tr '+/' '-_' | tr -d '=').sig"; }

[ -e "$DATA" ] && { echo "refusing: $DATA already exists"; exit 2; }
mkdir -p "$WORK"
"$PGBIN/initdb" -D "$DATA" -U postgres -A trust -E UTF8 --no-locale >/dev/null || exit 2
"$PGBIN/pg_ctl" -D "$DATA" -l "$WORK/pg.log" -o "-p $PORT -c listen_addresses=localhost" -w start >/dev/null || exit 2
trap '"$PGBIN/pg_ctl" -D "$DATA" -m fast -w stop >/dev/null' EXIT
"$PGBIN/createdb" -h localhost -p "$PORT" -U postgres "$DB" || exit 2
pg -f "$HERE/suite_rls_fixture.sql" >/dev/null || exit 2
J1=$(jwt '{"sub":"00000000-0000-0000-0000-0000000000a1","session_id":"00000000-0000-0000-0000-00000000aaa1","iat":1763000000,"exp":1763003600,"aal":"aal1"}')
J3=$(jwt '{"sub":"00000000-0000-0000-0000-0000000000c1","session_id":"00000000-0000-0000-0000-00000000ccc1","iat":1763100000,"exp":1763103600,"aal":"aal1"}')
pg >/dev/null <<SQL
create schema auth;
create table auth.users (id uuid primary key, email text, created_at timestamptz default now());
insert into auth.users (id, email) values ('00000000-0000-0000-0000-0000000000a1', 'a@example.invalid'),
  ('00000000-0000-0000-0000-0000000000b1', 'b@example.invalid'), ('00000000-0000-0000-0000-0000000000c1', 'c@example.invalid');
insert into public.suite_users (id, external_id, email) values ('00000000-0000-0000-0000-0000000000f1', 'profile-a', 'a@example.invalid');
insert into public.suite_saved_items (user_id, app, item_type, item_key, title, payload, valid) values
  ('00000000-0000-0000-0000-0000000000f1', '_auth_browser', 'browser_session', 'sid-secret-1', 'session',
   jsonb_build_object('access_token', '$J1', 'refresh_token', 'fake-refresh-1'), true),
  ('00000000-0000-0000-0000-0000000000f1', '_auth_browser', 'browser_session', 'sid-secret-3', 'session',
   jsonb_build_object('access_token', '$J3', 'refresh_token', 'fake-refresh-3'), false),
  ('00000000-0000-0000-0000-0000000000f1', '_auth_browser', 'browser_session', 'sid-secret-x', 'session',
   '{"access_token": "not-a-jwt", "refresh_token": "fake-refresh-x"}', true);
SQL
NB=$(q "select count(*) from public.suite_saved_items where app = '_auth_browser' and item_type = 'browser_session'")
NV=$(q "select count(*) from public.suite_saved_items where app = '_auth_browser' and item_type = 'browser_session' and valid")
NO=$(q "select count(*) from public.suite_saved_items where not (app = '_auth_browser' and item_type = 'browser_session')")
NU=$(q "select count(*) from public.suite_saved_items where app = '_auth_browser' and item_type = 'browser_session' and coalesce(payload->>'access_token', '') not like 'eyJ%'")
echo "fixture: $NB browser-session rows ($NV valid), $NO other saved items, 3 Auth users"

echo "Refuses or rolls back, leaving nothing behind"
before=$(fp_all)
run_with "$NB" "$NO" 4; grep -q "refused: 3 Auth users, expected 4" "$WORK/out.txt" && ok "refuses on the wrong project" || bad "wrong project" "$(cat "$WORK/out.txt")"
run_with 99 "$NO" 3; grep -q "refused: $NB browser-session rows, expected 99" "$WORK/out.txt" && ok "refuses on a row-count mismatch" || bad "row mismatch" "$(cat "$WORK/out.txt")"
q "create function public._qa_touch() returns trigger language plpgsql as \$\$ begin update public.suite_saved_items set title = title || '!' where id = (select min(id) from public.suite_saved_items where app <> '_auth_browser'); return new; end \$\$; create trigger _qa_touch after update on public.suite_saved_items for each row when (new.app = '_auth_browser' and new.item_key not like 'trigger-selftest-%') execute function public._qa_touch();" >/dev/null
run_with "$NB" "$NO" 3; grep -q "rolled back: other saved items changed" "$WORK/out.txt" && ok "rolls back when another saved item changes" || bad "fingerprint rollback" "$(cat "$WORK/out.txt")"
q "drop trigger _qa_touch on public.suite_saved_items; drop function public._qa_touch();" >/dev/null
equals "$(fp_all)" "$before" "  saved items unchanged after the refusals and the rollback"
equals "$(schema_state)/$(trig_state)" "0/0" "  no evidence schema and no trigger left behind"

echo "Applies"
other=$(fp_other)
run_with "$NB" "$NO" 3; grep -q "OK: evidence snapshot $NB rows; trigger installed and self-tested; revoked $NB browser-session rows ($NV had been valid); $NO other saved items unchanged" "$WORK/out.txt" && ok "snapshot + trigger + revocation in one run" || bad "applies" "$(cat "$WORK/out.txt")"
grep -q "^$NB|0|0|$NO|$NB|t$" "$WORK/out.txt" && ok "verify query: $NB | 0 | 0 | $NO | $NB | true" || bad "verify query" "$(tail -2 "$WORK/out.txt")"
equals "$(fp_other)" "$other" "other saved items byte-for-byte unchanged"
equals "$(q "select count(*) from public.suite_saved_items where item_key like 'trigger-selftest-%'")" "0" "self-test row removed"

echo "Evidence snapshot"
snap=$(q "select row_to_json(s)::text from security_audit.suite_sid_bridge_snapshot_20261124 s")
echo "$snap" | grep -qE "fake-refresh|not-a-jwt|eyJ|sid-secret" && bad "holds no token and no raw sid" "$snap" || ok "holds no token and no raw sid"
equals "$(q "select count(*) from security_audit.suite_sid_bridge_snapshot_20261124 where sid_sha256 = encode(sha256(convert_to('sid-secret-1', 'UTF8')), 'hex')")" "1" "sid kept only as SHA-256 (matchable to a known link)"
equals "$(q "select token_auth_user_id || '|' || token_session_id || '|' || token_issued_at::date || '|' || token_aal from security_audit.suite_sid_bridge_snapshot_20261124 where valid_before and token_auth_user_id is not null")" "00000000-0000-0000-0000-0000000000a1|00000000-0000-0000-0000-00000000aaa1|$(q "select to_timestamp(1763000000)::date")|aal1" "keeps account, session, issue time and level from the token claims"
equals "$(q "select count(*) from security_audit.suite_sid_bridge_snapshot_20261124 where token_auth_user_id is null and had_refresh_token")" "$NU" "an unreadable token is recorded as unreadable, not fatal"
equals "$(q "select has_schema_privilege('anon', 'security_audit', 'USAGE')::text || has_table_privilege('authenticated', 'security_audit.suite_sid_bridge_snapshot_20261124', 'SELECT')::text")" "falsefalse" "not reachable by anon or authenticated"

echo "Trigger blocks old apps from now on"
q "insert into public.suite_saved_items (user_id, app, item_type, item_key, title, payload, valid) values ('00000000-0000-0000-0000-0000000000f1', '_auth_browser', 'browser_session', 'sid-new-old-app', 'session', '{\"access_token\": \"t\", \"refresh_token\": \"r\"}', true)" >/dev/null
equals "$(q "select valid::text || '|' || (payload ? 'refresh_token')::text from public.suite_saved_items where item_key = 'sid-new-old-app'")" "false|false" "a new record written by an old app is stored revoked (write still succeeds)"
q "update public.suite_saved_items set payload = '{\"access_token\": \"t2\", \"refresh_token\": \"r2\"}', valid = true where item_key = 'sid-secret-1'" >/dev/null
equals "$(q "select valid::text || '|' || (payload ? 'refresh_token')::text from public.suite_saved_items where item_key = 'sid-secret-1'")" "false|false" "an old app re-saving tokens into an existing record is neutralised"
q "update public.suite_saved_items set title = 'renamed' where id = (select min(id) from public.suite_saved_items where app <> '_auth_browser')" >/dev/null
equals "$(q "select count(*) from public.suite_saved_items where title = 'renamed'")" "1" "other saved items still save normally"

echo "Second run"
run_with "$NB" "$NO" 3; grep -q "refused: \|rolled back" "$WORK/out.txt" && ok "refuses to run twice (snapshot preserved)" || bad "second run" "$(cat "$WORK/out.txt")"
equals "$(q "select count(*) from security_audit.suite_sid_bridge_snapshot_20261124")" "$NB" "  original evidence untouched"

echo; echo "passed $PASS, failed $FAIL"
[ "$FAIL" -eq 0 ]
