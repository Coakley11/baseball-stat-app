#!/usr/bin/env bash
# Tests docs/sql/baseball_shared_containment_*.sql against a throwaway local PostgreSQL cluster built
# from suite_rls_fixture.sql + baseball_shared_fixture.sql. Never touches a real project.
#
#   scripts/sql_tests/baseball_shared_containment_local_test.sh <empty scratch dir> [pg bin dir] [port]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SQL="$HERE/../../docs/sql"
STEP="$SQL/baseball_shared_containment_stepB_DRAFT.sql"
PREFLIGHT="$SQL/baseball_shared_containment_preflight.sql"
VERIFY="$SQL/baseball_shared_containment_verify.sql"
ROLLBACK_FALLBACK="$SQL/baseball_shared_containment_rollback_DRAFT.sql"
WORK="${1:?usage: $0 <scratch dir> [pg bin dir] [port]}"
PGBIN="${2:-/c/Program Files/PostgreSQL/17/bin}"
PORT="${3:-55438}"
DATA="$WORK/pgdata"
DB=suite
PASS=0
FAIL=0
BB="('baseball_shared_draft_rooms', 'baseball_shared_leagues')"

pg() { "$PGBIN/psql" -X -q -tA -v ON_ERROR_STOP=1 -h localhost -p "$PORT" -U postgres -d "$DB" "$@"; }
psql_as() { local role="$1" body="$2"; [ "$role" != "-" ] && body="set role $role; $body"; pg -c "$body" 2>&1; }
ok()  { PASS=$((PASS + 1)); echo "  ok    $1"; }
bad() { FAIL=$((FAIL + 1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && echo "        $2"; }
allowed() { local out; if out=$(psql_as "$1" "$2"); then ok "$3"; else bad "$3" "$out"; fi; }
denied() {
  local out; out=$(psql_as "$1" "$2")
  if [ $? -ne 0 ] && echo "$out" | grep -q "permission denied"; then ok "$3"; else bad "$3" "$out"; fi
}
equals() { if [ "$1" = "$2" ]; then ok "$3"; else bad "$3" "expected [$2] got [$1]"; fi; }
section() { psql_as - "$(sed -n "/^-- $1\./,/^-- $2\./p" "$PREFLIGHT" | grep -v '^--')"; }
run_file() { pg -f "$1" >/dev/null 2>"$WORK/last_err.txt"; }
# Everything Step B could change, or must not: RLS flags and every ACL on the two tables, plus the suite tables.
state() {
  psql_as - "select c.relname, c.relrowsecurity, coalesce((select string_agg(pg_get_userbyid(a.grantee) || ':' || a.privilege_type, ',' order by 1) from aclexplode(c.relacl) a), '') from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind = 'r' order by c.relname"
}
fingerprints() {
  psql_as - "select 'rooms', count(*), md5(coalesce(string_agg(md5(x::text), ',' order by md5(x::text)), '')) from public.baseball_shared_draft_rooms x union all select 'leagues', count(*), md5(coalesce(string_agg(md5(x::text), ',' order by md5(x::text)), '')) from public.baseball_shared_leagues x"
}
fresh_db() {
  "$PGBIN/dropdb" -h localhost -p "$PORT" -U postgres --if-exists "$DB"
  "$PGBIN/createdb" -h localhost -p "$PORT" -U postgres "$DB" || exit 2
  run_file "$HERE/suite_rls_fixture.sql" || { cat "$WORK/last_err.txt"; exit 2; }
  run_file "$HERE/baseball_shared_fixture.sql" || { cat "$WORK/last_err.txt"; exit 2; }
}
step_must_abort() {
  local before after
  before="$(state)$(fingerprints)"
  if run_file "$STEP"; then bad "$1: Step B refuses" "it applied"
  elif grep -qE "ABORTED, nothing changed: .*$2" "$WORK/last_err.txt"; then
    ok "$1: Step B refuses ($(grep -oE 'ABORTED[^"]*' "$WORK/last_err.txt" | head -1 | cut -c1-90))"
  else bad "$1: Step B refuses for the right reason" "$(cat "$WORK/last_err.txt")"; fi
  after="$(state)$(fingerprints)"
  equals "$after" "$before" "$1: no RLS flag, privilege or row changed"
}

[ -e "$DATA" ] && { echo "refusing: $DATA already exists"; exit 2; }
mkdir -p "$WORK"
"$PGBIN/initdb" -D "$DATA" -U postgres -A trust -E UTF8 --no-locale >/dev/null || exit 2
"$PGBIN/pg_ctl" -D "$DATA" -l "$WORK/pg.log" -o "-p $PORT -c listen_addresses=localhost" -w start >/dev/null || exit 2
trap '"$PGBIN/pg_ctl" -D "$DATA" -m fast -w stop >/dev/null' EXIT
fresh_db

echo "The exposure as found"
equals "$(psql_as anon "select count(*) from public.baseball_shared_draft_rooms")" "3" "anon lists every shared draft room"
equals "$(psql_as anon "select shared_room_json->>'invite' from public.baseball_shared_draft_rooms where room_code = 'FAKE-ROOM-1'")" "fake-invite-token" "anon reads a room's invite token"
allowed authenticated "update public.baseball_shared_leagues set revision = revision + 1" "any signed-in user can edit a league"
allowed anon "delete from public.baseball_shared_draft_rooms where room_code = 'FAKE-ROOM-3'" "anon can delete a room"
fresh_db

echo "Preflight is read-only and reports the exposure"
if PGOPTIONS="-c default_transaction_read_only=on" run_file "$PREFLIGHT"; then ok "preflight runs inside a read-only transaction"
else bad "preflight runs inside a read-only transaction" "$(cat "$WORK/last_err.txt")"; fi
D1="$(section D1 D1b)"
echo "$D1" | grep -q "^baseball_shared_draft_rooms|f|f|0|anon|t|t|t|t|t|t|t$" && ok "D1 shows anon holding every privilege, RLS off" || bad "D1 shows the exposure" "$D1"
D3="$(section D3 D4)"
equals "$D3" "0|0|0|0|0|0|0" "D3: no view, definer function, PUBLIC grant, serial column, publication or trigger"
D4="$(section D4 D5)"
echo "$D4" | grep -q "^baseball_shared_draft_rooms|3|.*|3|.*|1|in_progress=1, not_started=2|" && ok "D4 counts rooms and statuses" || bad "D4 counts rooms" "$D4"
echo "$D4" | grep -q "acct_\|(empty)=1" && ok "D4 labels hosts and counts the unrecognised host" || bad "D4 host labels" "$D4"
if echo "$D4$D1$(section D1b D2)$(section D5 ZZ 2>/dev/null)" | grep -qE "FAKE-ROOM|FAKE-LEAGUE|fake-invite|outsider|[0-9a-f]{8}-[0-9a-f]{4}-"; then bad "preflight returns no room code, league id, invite, content or user id"
else ok "preflight returns no room code, league id, invite, content or user id"; fi
STATE_BEFORE="$(state)"
FP_BEFORE="$(fingerprints)"
section D2 D3 > "$WORK/generated_rollback.sql"
equals "$(grep -c . "$WORK/generated_rollback.sql")" "6" "D2 generates 4 grants (2 roles x 2 tables) and 2 RLS lines"

SUITE_Q="select c.relname, c.relrowsecurity, coalesce((select string_agg(pg_get_userbyid(a.grantee) || ':' || a.privilege_type, ',' order by 1) from aclexplode(c.relacl) a), '') from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind = 'r' and c.relname like 'suite\_%' order by c.relname"
BB_ACL_Q="select md5(string_agg(c.relname || ':' || pg_get_userbyid(a.grantee) || ':' || a.privilege_type, ',' order by 1)) from pg_class c cross join lateral aclexplode(c.relacl) a where c.relname in $BB and a.grantee in ('anon'::regrole, 'authenticated'::regrole)"
SR_Q="select string_agg(c.relname || ':' || a.privilege_type, ',' order by 1) from pg_class c cross join lateral aclexplode(c.relacl) a where c.relname in $BB and a.grantee = 'service_role'::regrole"
BB_RLS_Q="select string_agg(relname || '=' || relrowsecurity, ',' order by 1) from pg_class where relname in $BB"
SUITE_BEFORE="$(psql_as - "$SUITE_Q")"
SR_BEFORE="$(psql_as - "$SR_Q")"
BB_ACL_BEFORE="$(psql_as - "$BB_ACL_Q")"
BB_RLS_BEFORE="$(psql_as - "$BB_RLS_Q")"

echo "Step B"
run_file "$STEP" && ok "Step B applies" || bad "Step B applies" "$(cat "$WORK/last_err.txt")"
equals "$(fingerprints)" "$FP_BEFORE" "no row changed (counts and content fingerprints identical)"
equals "$(psql_as - "$SUITE_Q")" "$SUITE_BEFORE" "every suite table's RLS flag and ACL untouched"
equals "$(psql_as - "$SR_Q")" "$SR_BEFORE" "service_role grants on the two tables identical"
equals "$(psql_as - "select count(*) from pg_class c cross join lateral aclexplode(c.relacl) a where c.relname in $BB and a.grantee = 'service_role'::regrole")" "16" \
  "service_role still holds all eight privileges (PostgreSQL 17 includes MAINTAIN) on each table"
for t in baseball_shared_draft_rooms baseball_shared_leagues; do
  for r in anon authenticated; do
    denied $r "select 1 from public.$t limit 1" "$r cannot read $t"
    denied $r "delete from public.$t" "$r cannot delete from $t"
    denied $r "truncate public.$t" "$r cannot truncate $t"
  done
done
denied anon "insert into public.baseball_shared_draft_rooms (room_code) values ('X')" "anon cannot create a room"
denied authenticated "update public.baseball_shared_leagues set revision = 99" "a signed-in user cannot edit a league"
denied anon "update public.baseball_shared_draft_rooms set status = 'finished'" "anon cannot edit a room"

echo "service_role keeps working (the Baseball app's own operations)"
allowed service_role "insert into public.baseball_shared_draft_rooms (room_code, host_user_id, shared_room_json, revision, status)
  values ('NEW-ROOM', '00000000-0000-0000-0000-00000000000a', '{}', 1, 'not_started')
  on conflict (room_code) do update set shared_room_json = excluded.shared_room_json, revision = excluded.revision" \
  "create/upsert a shared room (merge-duplicates on room_code)"
allowed service_role "update public.baseball_shared_draft_rooms set revision = 4, status = 'in_progress' where room_code = 'FAKE-ROOM-1' and revision = 3" \
  "advance a room (compare-and-set on revision)"
allowed service_role "select shared_room_json from public.baseball_shared_draft_rooms where room_code = 'FAKE-ROOM-1'" "join/read a room"
allowed service_role "insert into public.baseball_shared_draft_rooms (room_code) values ('PROBE-1'); delete from public.baseball_shared_draft_rooms where room_code = 'PROBE-1'" \
  "health probe: insert then delete a probe room"
allowed service_role "insert into public.baseball_shared_leagues (league_id, draft_fingerprint, shared_league_json) values ('NEW-LEAGUE', 'fp2', '{}')
  on conflict (league_id) do update set shared_league_json = excluded.shared_league_json, revision = public.baseball_shared_leagues.revision + 1" \
  "league upsert"
allowed service_role "select league_id, shared_league_json from public.baseball_shared_leagues where draft_fingerprint = 'fp1'" "league read by draft fingerprint"
allowed service_role "update public.baseball_shared_leagues set revision = revision + 1 where league_id = 'FAKE-LEAGUE-1'" "league revision bump"
FP_AFTER_SR="$(fingerprints)"

echo "Verification script"
if PGOPTIONS="-c default_transaction_read_only=on" run_file "$VERIFY"; then ok "verify script runs read-only"
else bad "verify script runs read-only" "$(cat "$WORK/last_err.txt")"; fi
VB1="$(psql_as - "$(sed -n '/^-- VB1\./,/^-- VB2\./p' "$VERIFY" | grep -v '^--')" | tr -d '\r')"
equals "$VB1" "$(printf 'baseball_shared_draft_rooms|t|f|0\nbaseball_shared_leagues|t|f|0')" "VB1: RLS on, not forced, no policies"
VB2="$(psql_as - "$(sed -n '/^-- VB2\./,/^-- VB3\./p' "$VERIFY" | grep -v '^--')")"
equals "$(echo "$VB2" | grep -c '|anon|f|f|f|f|f|f|f|f|f$')" "2" "VB2: anon holds nothing on both tables"
equals "$(echo "$VB2" | grep -c '|authenticated|f|f|f|f|f|f|f|f|f$')" "2" "VB2: authenticated holds nothing on both tables"
equals "$(echo "$VB2" | grep -c '|service_role|t|t|t|t|t|t|t|t|t$')" "2" "VB2: service_role holds everything"

echo "Re-running Step B is safe"
run_file "$STEP" && ok "Step B applies a second time (idempotent)" || bad "Step B idempotent" "$(cat "$WORK/last_err.txt")"
equals "$(fingerprints)" "$FP_AFTER_SR" "idempotent run changes no row"

echo "Rollback from the statements preflight D2 generated"
FP_BEFORE_ROLLBACK="$(fingerprints)"
if psql_as - "begin; $(cat "$WORK/generated_rollback.sql") commit;" >/dev/null; then ok "generated rollback applies"; else bad "generated rollback applies"; fi
equals "$(psql_as - "$BB_ACL_Q")" "$BB_ACL_BEFORE" "anon / authenticated privileges exactly as before containment"
equals "$(psql_as - "$BB_RLS_Q")" "$BB_RLS_BEFORE" "RLS flags exactly as before containment"
equals "$(psql_as - "$SR_Q")" "$SR_BEFORE" "service_role grants still identical"
equals "$(fingerprints)" "$FP_BEFORE_ROLLBACK" "rollback changes no row"
allowed anon "select count(*) from public.baseball_shared_draft_rooms" "anon can read again after rollback (as before containment)"

echo "Fallback rollback file also restores the exposure"
fresh_db
run_file "$STEP"
run_file "$ROLLBACK_FALLBACK" && ok "fallback rollback applies" || bad "fallback rollback applies" "$(cat "$WORK/last_err.txt")"
allowed anon "select count(*) from public.baseball_shared_leagues" "anon can read again after the fallback rollback"

echo "Bypass paths: Step B refuses and changes nothing"
fresh_db
psql_as - "grant select on public.baseball_shared_leagues to public" >/dev/null
step_must_abort "PUBLIC grant" "PUBLIC holds privileges"
psql_as - "revoke all on public.baseball_shared_draft_rooms, public.baseball_shared_leagues from anon, authenticated" >/dev/null
allowed anon "select count(*) from public.baseball_shared_leagues" "why: after a plain revoke from anon, PUBLIC still lets anon read"

fresh_db
psql_as - "create view public.v_rooms as select * from public.baseball_shared_draft_rooms; grant select on public.v_rooms to anon" >/dev/null
step_must_abort "anon-readable view" "views reachable"
psql_as - "alter table public.baseball_shared_draft_rooms enable row level security; revoke all on public.baseball_shared_draft_rooms from anon" >/dev/null
allowed anon "select count(*) from public.v_rooms" "why: after RLS + revoke, an owner's view still reads past both"

fresh_db
psql_as - "create function public.f_rooms() returns setof public.baseball_shared_draft_rooms language sql security definer as 'select * from public.baseball_shared_draft_rooms'" >/dev/null
step_must_abort "anon-callable security definer function" "security definer functions"

fresh_db
psql_as - "create role leaky nologin; grant select on public.baseball_shared_leagues to leaky; grant leaky to anon" >/dev/null
step_must_abort "role membership" "belong to roles with access"
psql_as - "revoke leaky from anon; drop owned by leaky; drop role leaky" >/dev/null

fresh_db
psql_as - "create role maint nologin; revoke all on public.baseball_shared_leagues from public; grant maintain on public.baseball_shared_leagues to maint; grant maint to anon" >/dev/null
step_must_abort "role membership holding only MAINTAIN" "belong to roles with access"
psql_as - "revoke maint from anon; drop owned by maint; drop role maint" >/dev/null

fresh_db
psql_as - "revoke delete on public.baseball_shared_draft_rooms from service_role" >/dev/null
step_must_abort "service_role missing a grant" "service_role lacks DELETE"

fresh_db
psql_as - "alter role service_role nobypassrls" >/dev/null
step_must_abort "service_role without BYPASSRLS" "does not bypass RLS"
psql_as - "alter role service_role bypassrls" >/dev/null

fresh_db
psql_as - "alter table public.baseball_shared_leagues add column n bigint generated always as identity" >/dev/null
step_must_abort "a sequence appears on a table" "serial/identity columns"

fresh_db
pg -c "begin; lock table public.baseball_shared_leagues in access share mode; select pg_sleep(12); commit;" >/dev/null 2>&1 &
HOLDER=$!
sleep 2
step_must_abort "table busy (lock held 12s)" "|lock timeout"
wait $HOLDER
if grep -q "canceling statement due to lock timeout" "$WORK/last_err.txt"; then ok "busy table: gave up after the 5s lock timeout"; else bad "busy table: lock timeout" "$(cat "$WORK/last_err.txt")"; fi

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
