#!/usr/bin/env bash
# Tests docs/sql/suite_rls_containment_*.sql against a throwaway local PostgreSQL cluster
# built from scripts/sql_tests/suite_rls_fixture.sql. Never touches a real project.
#
#   scripts/sql_tests/suite_rls_containment_local_test.sh <empty scratch dir> [pg bin dir] [port]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SQL="$HERE/../../docs/sql"
STEP1="$SQL/suite_rls_containment_step1_DRAFT.sql"
STEP2="$SQL/suite_rls_containment_step2_DRAFT.sql"
PREFLIGHT="$SQL/suite_rls_containment_preflight.sql"
WORK="${1:?usage: $0 <scratch dir> [pg bin dir] [port]}"
PGBIN="${2:-/c/Program Files/PostgreSQL/17/bin}"
PORT="${3:-55432}"
DATA="$WORK/pgdata"
DB=suite
PASS=0
FAIL=0

pg() { "$PGBIN/psql" -X -q -tA -v ON_ERROR_STOP=1 -h localhost -p "$PORT" -U postgres -d "$DB" "$@"; }
psql_as() {  # psql_as <role|-> <sql> : run as postgres, after SET ROLE when a role is given
  local role="$1" body="$2"
  [ "$role" != "-" ] && body="set role $role; $body"
  pg -c "$body" 2>&1
}
ok()     { PASS=$((PASS + 1)); echo "  ok    $1"; }
bad()    { FAIL=$((FAIL + 1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && echo "        $2"; }
allowed() { local out; if out=$(psql_as "$1" "$2"); then ok "$3"; else bad "$3" "$out"; fi; }
denied()  {
  local out; out=$(psql_as "$1" "$2")
  if [ $? -ne 0 ] && echo "$out" | grep -q "permission denied"; then ok "$3"; else bad "$3" "$out"; fi
}
equals() { if [ "$1" = "$2" ]; then ok "$3"; else bad "$3" "expected [$2] got [$1]"; fi; }
section() { psql_as - "$(sed -n "/^-- $1\./,/^-- $2\./p" "$PREFLIGHT" | grep -v '^--')"; }
fingerprints() { section C6 C7; }
privileges()   { section C1 C2; }
run_file() { pg -f "$1" >/dev/null 2>"$WORK/last_err.txt"; }
fresh_db() {
  "$PGBIN/dropdb" -h localhost -p "$PORT" -U postgres --if-exists "$DB"
  "$PGBIN/createdb" -h localhost -p "$PORT" -U postgres "$DB" || exit 2
  run_file "$HERE/suite_rls_fixture.sql" || { cat "$WORK/last_err.txt"; exit 2; }
}
# step1_must_abort <label> <reason regex>: Step 1 refuses, and nothing at all changed.
step1_must_abort() {
  local before after
  before="$(privileges)$(fingerprints)"
  if run_file "$STEP1"; then
    bad "$1: Step 1 refuses" "it applied"
  elif grep -qE "ABORTED, nothing changed: .*$2" "$WORK/last_err.txt"; then
    ok "$1: Step 1 refuses ($(grep -oE 'ABORTED[^"]*' "$WORK/last_err.txt" | head -1 | cut -c1-90))"
  else
    bad "$1: Step 1 refuses for the right reason" "$(cat "$WORK/last_err.txt")"
  fi
  after="$(privileges)$(fingerprints)"
  equals "$after" "$before" "$1: no RLS flag, privilege or row changed"
}

[ -e "$DATA" ] && { echo "refusing: $DATA already exists"; exit 2; }
mkdir -p "$WORK"
"$PGBIN/initdb" -D "$DATA" -U postgres -A trust -E UTF8 --no-locale >/dev/null || exit 2
"$PGBIN/pg_ctl" -D "$DATA" -l "$WORK/pg.log" -o "-p $PORT -c listen_addresses=localhost" -w start >/dev/null || exit 2
trap '"$PGBIN/pg_ctl" -D "$DATA" -m fast -w stop >/dev/null' EXIT
fresh_db

echo "Before containment: the exposure as found"
equals "$(psql_as anon "select payload->>'refresh_token' from public.suite_saved_items where item_type = 'browser_session'")" \
  "fake-refresh-a" "anon reads another account's stored refresh token"
allowed anon "update public.suite_user_settings set settings = settings where user_id = '00000000-0000-0000-0000-00000000000b'" \
  "anon can update another account's settings"
allowed anon "select count(*) from public.suite_users" "anon lists suite_users"
equals "$(psql_as anon "select count(*) from public.suite_app_current_state")" "0" \
  "RLS-on table: anon sees no rows"

echo "Preflight is read-only"
if PGOPTIONS="-c default_transaction_read_only=on" run_file "$PREFLIGHT"; then
  ok "preflight runs inside a read-only transaction"
else bad "preflight runs inside a read-only transaction" "$(cat "$WORK/last_err.txt")"; fi
FP_BEFORE="$(fingerprints)"
PRIV_BEFORE="$(privileges)"
ROLLBACK_SQL="$(section C2 C3)"
printf '%s\n' "$ROLLBACK_SQL" > "$WORK/generated_rollback.sql"

echo "Step 1"
SR_BEFORE="$(psql_as - "select string_agg(c.relname || ':' || a.privilege_type, ',' order by 1) from pg_class c cross join lateral aclexplode(c.relacl) a where c.relname like 'suite\_%' and a.grantee = 'service_role'::regrole")"
run_file "$STEP1" && ok "Step 1 applies" || bad "Step 1 applies" "$(cat "$WORK/last_err.txt")"
equals "$(fingerprints)" "$FP_BEFORE" "no row changed (counts and content fingerprints identical)"
equals "$(psql_as - "select string_agg(c.relname || ':' || a.privilege_type, ',' order by 1) from pg_class c cross join lateral aclexplode(c.relacl) a where c.relname like 'suite\_%' and a.grantee = 'service_role'::regrole")" \
  "$SR_BEFORE" "every service_role grant identical"
for t in suite_users suite_saved_items suite_user_settings; do
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
equals "$(psql_as anon "select count(*) from public.suite_app_current_state")" "0" \
  "Step 1 leaves the other three as they were (RLS still hides every row)"

echo "service_role keeps working (the suite apps' own operations)"
allowed service_role "select count(*) from public.suite_users where external_id = 'fixture_a'" "find_user_rows"
allowed service_role "select payload->>'refresh_token' from public.suite_saved_items where item_type = 'browser_session'" "load_browser_auth_session"
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

echo "Verification script"
if PGOPTIONS="-c default_transaction_read_only=on" run_file "$SQL/suite_rls_containment_verify.sql"; then
  ok "verify script runs read-only"
else bad "verify script runs read-only" "$(cat "$WORK/last_err.txt")"; fi

echo "Re-running Step 1 is safe"
run_file "$STEP1" && ok "Step 1 applies a second time (idempotent)" || bad "Step 1 idempotent" "$(cat "$WORK/last_err.txt")"

echo "Step 2"
run_file "$STEP2" && ok "Step 2 applies" || bad "Step 2 applies" "$(cat "$WORK/last_err.txt")"
for t in suite_activity_events suite_app_current_state suite_resume_items; do
  denied anon "select 1 from public.$t limit 1" "anon cannot read $t"
done
allowed service_role "insert into public.suite_resume_items (app, item_key, title, user_id) values ('applied_intelligence', 'ai:question:2', 'C', '00000000-0000-0000-0000-00000000000a')" \
  "upsert_resume_item insert after Step 2"
equals "$(psql_as - "select bool_and(relrowsecurity) from pg_class where relnamespace = 'public'::regnamespace and relname like 'suite\_%' and relkind = 'r'")" \
  "t" "V1: RLS on for all six tables"

echo "Rollback from the statements preflight C2 generated"
FP_AFTER="$(fingerprints)"
if psql_as - "begin; $ROLLBACK_SQL commit;" >/dev/null; then ok "generated rollback applies"; else bad "generated rollback applies"; fi
equals "$(privileges)" "$PRIV_BEFORE" "RLS flags and every role's privileges are exactly as before containment"
equals "$(fingerprints)" "$FP_AFTER" "rollback changes no row"

echo "Bypass paths: Step 1 refuses and changes nothing"
fresh_db
psql_as - "grant select on public.suite_users to public" >/dev/null
step1_must_abort "PUBLIC grant" "PUBLIC holds privileges"
psql_as - "revoke all on public.suite_users, public.suite_saved_items, public.suite_user_settings from anon, authenticated" >/dev/null
allowed anon "select count(*) from public.suite_users" "why: after a plain revoke from anon, PUBLIC still lets anon read"

fresh_db
psql_as - "create view public.v_profiles as select * from public.suite_users; grant select on public.v_profiles to anon" >/dev/null
step1_must_abort "anon-readable view" "views reachable"
psql_as - "alter table public.suite_users enable row level security; revoke all on public.suite_users from anon" >/dev/null
allowed anon "select count(*) from public.v_profiles" "why: after RLS + revoke, an owner's view still reads past both"

fresh_db
psql_as - "create function public.f_tokens() returns setof public.suite_saved_items language sql security definer as 'select * from public.suite_saved_items'" >/dev/null
step1_must_abort "anon-callable security definer function" "security definer functions"

fresh_db
psql_as - "create role leaky nologin; grant select on public.suite_saved_items to leaky; grant leaky to anon" >/dev/null
step1_must_abort "role membership" "belong to roles with access"
psql_as - "revoke leaky from anon; drop owned by leaky; drop role leaky" >/dev/null

fresh_db
psql_as - "revoke delete on public.suite_users from service_role" >/dev/null
step1_must_abort "service_role missing a grant" "service_role lacks DELETE"

fresh_db
psql_as - "alter role service_role nobypassrls" >/dev/null
step1_must_abort "service_role without BYPASSRLS" "does not bypass RLS"
psql_as - "alter role service_role bypassrls" >/dev/null

fresh_db
pg -c "begin; lock table public.suite_users in access share mode; select pg_sleep(12); commit;" >/dev/null 2>&1 &
HOLDER=$!
sleep 2
step1_must_abort "table busy (lock held 12s)" "|lock timeout"
wait $HOLDER
if grep -q "canceling statement due to lock timeout" "$WORK/last_err.txt"; then ok "busy table: gave up after the 5s lock timeout"; else bad "busy table: lock timeout" "$(cat "$WORK/last_err.txt")"; fi

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
