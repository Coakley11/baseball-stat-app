#!/usr/bin/env bash
# Tests docs/sql/suite_rls_containment_*.sql against a throwaway local PostgreSQL cluster
# built from scripts/sql_tests/suite_rls_fixture.sql. Never touches a real project.
#
#   scripts/sql_tests/suite_rls_containment_local_test.sh <empty scratch dir> [pg bin dir] [port]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SQL="$HERE/../../docs/sql"
WORK="${1:?usage: $0 <scratch dir> [pg bin dir] [port]}"
PGBIN="${2:-/c/Program Files/PostgreSQL/17/bin}"
PORT="${3:-55432}"
DATA="$WORK/pgdata"
PASS=0
FAIL=0

psql_as() {  # psql_as <role|-> <sql> : run as postgres, after SET ROLE when a role is given
  local role="$1" body="$2"
  [ "$role" != "-" ] && body="set role $role; $body"
  "$PGBIN/psql" -X -q -tA -v ON_ERROR_STOP=1 -h localhost -p "$PORT" -U postgres -d suite -c "$body" 2>&1
}
ok()     { PASS=$((PASS + 1)); echo "  ok    $1"; }
bad()    { FAIL=$((FAIL + 1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && echo "        $2"; }
allowed() { local out; if out=$(psql_as "$1" "$2"); then ok "$3"; else bad "$3" "$out"; fi; }
denied()  {
  local out; out=$(psql_as "$1" "$2")
  if [ $? -ne 0 ] && echo "$out" | grep -q "permission denied"; then ok "$3"; else bad "$3" "$out"; fi
}
equals() { if [ "$1" = "$2" ]; then ok "$3"; else bad "$3" "expected [$2] got [$1]"; fi; }
fingerprints() { psql_as - "$(sed -n '/^-- C6\./,/^-- C7\./p' "$SQL/suite_rls_containment_preflight.sql" | grep -v '^--')"; }
privileges()   { psql_as - "$(sed -n '/^-- C1\./,/^-- C2\./p' "$SQL/suite_rls_containment_preflight.sql" | grep -v '^--')"; }
run_file() { "$PGBIN/psql" -X -q -v ON_ERROR_STOP=1 -h localhost -p "$PORT" -U postgres -d suite -f "$1" >/dev/null 2>"$WORK/last_err.txt"; }

[ -e "$DATA" ] && { echo "refusing: $DATA already exists"; exit 2; }
mkdir -p "$WORK"
"$PGBIN/initdb" -D "$DATA" -U postgres -A trust -E UTF8 --no-locale >/dev/null || exit 2
"$PGBIN/pg_ctl" -D "$DATA" -l "$WORK/pg.log" -o "-p $PORT -c listen_addresses=localhost" -w start >/dev/null || exit 2
trap '"$PGBIN/pg_ctl" -D "$DATA" -m fast -w stop >/dev/null' EXIT
"$PGBIN/createdb" -h localhost -p "$PORT" -U postgres suite || exit 2
run_file "$HERE/suite_rls_fixture.sql" || { cat "$WORK/last_err.txt"; exit 2; }

echo "Before containment: the exposure as found"
equals "$(psql_as anon "select payload->>'refresh_token' from public.suite_saved_items where item_type = 'browser_session'")" \
  "fake-refresh-a" "anon reads another account's stored refresh token"
allowed anon "update public.suite_user_settings set settings = settings where user_id = '00000000-0000-0000-0000-00000000000b'" \
  "anon can update another account's settings"
allowed anon "select count(*) from public.suite_users" "anon lists suite_users"
equals "$(psql_as anon "select count(*) from public.suite_app_current_state")" "0" \
  "RLS-on table: anon sees no rows"

echo "Preflight is read-only"
if PGOPTIONS="-c default_transaction_read_only=on" run_file "$SQL/suite_rls_containment_preflight.sql"; then
  ok "preflight runs inside a read-only transaction"
else bad "preflight runs inside a read-only transaction" "$(cat "$WORK/last_err.txt")"; fi
FP_BEFORE="$(fingerprints)"
PRIV_BEFORE="$(privileges)"
ROLLBACK_SQL="$(psql_as - "$(sed -n '/^-- C2\./,/^-- C3\./p' "$SQL/suite_rls_containment_preflight.sql" | grep -v '^--')")"
printf '%s\n' "$ROLLBACK_SQL" > "$WORK/generated_rollback.sql"

echo "Containment"
run_file "$SQL/suite_rls_containment_DRAFT.sql" && ok "containment script applies" \
  || bad "containment script applies" "$(cat "$WORK/last_err.txt")"
equals "$(fingerprints)" "$FP_BEFORE" "no row changed (counts and content fingerprints identical)"
for t in suite_users suite_saved_items suite_user_settings suite_activity_events suite_app_current_state suite_resume_items; do
  for r in anon authenticated; do
    denied $r "select 1 from public.$t limit 1" "$r cannot read $t"
    denied $r "delete from public.$t" "$r cannot delete from $t"
  done
done
denied anon "insert into public.suite_user_settings (user_id, app) values ('00000000-0000-0000-0000-00000000000b', 'x')" \
  "anon cannot insert settings"
denied anon "update public.suite_user_settings set settings = '{}'" "anon cannot update settings"
denied anon "select setval(pg_get_serial_sequence('public.suite_saved_items', 'id'), 1)" \
  "anon cannot reset the saved-items id sequence"

echo "service_role keeps working (the suite apps' own operations)"
allowed service_role "select count(*) from public.suite_users where external_id = 'fixture_a'" "find_user_rows"
allowed service_role "insert into public.suite_users (external_id, email) values ('fixture_c', 'c@example.invalid')" "ensure_user_row creates a profile"
allowed service_role "insert into public.suite_saved_items (user_id, app, item_type, item_key, title, payload)
  values ('00000000-0000-0000-0000-00000000000a', '_auth_browser', 'browser_session', 'sid-a', 'session', '{}')
  on conflict (user_id, app, item_type, item_key) do update set payload = excluded.payload, updated_at = now()" \
  "upsert_saved_item (on_conflict user_id,app,item_type,item_key)"
allowed service_role "insert into public.suite_saved_items (user_id, app, item_key, title)
  values ('00000000-0000-0000-0000-00000000000b', 'baseball', 'new', 'New')" "saved item insert uses the identity sequence"
allowed service_role "update public.suite_saved_items set valid = false where user_id = '00000000-0000-0000-0000-00000000000b' and item_key = 'q1'" \
  "invalidate_saved_item (PATCH)"
allowed service_role "insert into public.suite_user_settings (user_id, app, settings) values ('00000000-0000-0000-0000-00000000000a', '_global', '{}')
  on conflict (user_id, app) do update set settings = excluded.settings" "save_user_settings (merge-duplicates on PK)"
allowed service_role "select settings from public.suite_user_settings where user_id = '00000000-0000-0000-0000-00000000000a' and app = '_global'" "load_user_settings"
allowed service_role "update public.suite_app_current_state set summary = 's' where app = 'baseball' and user_id = '00000000-0000-0000-0000-00000000000a'" \
  "compare-and-set state PATCH"
allowed service_role "insert into public.suite_activity_events (app, event, user_id) values ('baseball', 'e', '00000000-0000-0000-0000-00000000000a')" "append_event"
allowed service_role "insert into public.suite_resume_items (app, item_key, title, user_id) values ('applied_intelligence', 'ai:question:2', 'C', '00000000-0000-0000-0000-00000000000a')" \
  "upsert_resume_item insert"

echo "Verification script"
if PGOPTIONS="-c default_transaction_read_only=on" run_file "$SQL/suite_rls_containment_verify.sql"; then
  ok "verify script runs read-only"
else bad "verify script runs read-only" "$(cat "$WORK/last_err.txt")"; fi
equals "$(psql_as - "select bool_and(relrowsecurity) from pg_class where relnamespace = 'public'::regnamespace and relname like 'suite\_%' and relkind = 'r'")" \
  "t" "V1: RLS on for all six tables"

echo "Rollback from the generated statements"
FP_AFTER="$(fingerprints)"
if psql_as - "begin; $ROLLBACK_SQL commit;" >/dev/null; then ok "generated rollback applies"; else bad "generated rollback applies"; fi
equals "$(privileges)" "$PRIV_BEFORE" "RLS flags and every role's privileges are exactly as before containment"
equals "$(fingerprints)" "$FP_AFTER" "rollback changes no row"
equals "$(psql_as anon "select count(*) from public.suite_users")" "3" "after rollback anon access is back as found"

echo "Re-apply (idempotent)"
run_file "$SQL/suite_rls_containment_DRAFT.sql" && ok "containment applies a second time" \
  || bad "containment applies a second time" "$(cat "$WORK/last_err.txt")"
denied anon "select 1 from public.suite_saved_items limit 1" "anon denied again"
run_file "$SQL/suite_rls_containment_DRAFT.sql" && ok "containment is idempotent (third run)" \
  || bad "containment is idempotent (third run)" "$(cat "$WORK/last_err.txt")"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
