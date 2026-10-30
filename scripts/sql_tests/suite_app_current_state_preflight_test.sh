#!/usr/bin/env bash
# Tests docs/sql/suite_app_current_state_preflight.sql against a throwaway local PostgreSQL
# cluster: every block runs read-only, flags each ownership case, and returns no user id,
# full email or row content. Never touches a real project.
#
#   scripts/sql_tests/suite_app_current_state_preflight_test.sh <empty scratch dir> [pg bin dir] [port]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PREFLIGHT="$HERE/../../docs/sql/suite_app_current_state_preflight.sql"
WORK="${1:?usage: $0 <scratch dir> [pg bin dir] [port]}"
PGBIN="${2:-/c/Program Files/PostgreSQL/17/bin}"
PORT="${3:-55437}"
DATA="$WORK/pgdata"
DB=suite
PASS=0
FAIL=0

pg() { "$PGBIN/psql" -X -q -tA -F'|' -v ON_ERROR_STOP=1 -h localhost -p "$PORT" -U postgres -d "$DB" "$@"; }
ok()  { PASS=$((PASS + 1)); echo "  ok    $1"; }
bad() { FAIL=$((FAIL + 1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && echo "        $2"; }
# block <first line pattern>: one preflight block (from its header comment to the next header), read-only.
block() {
  awk -v start="$1" 'index($0, start) == 1 {on = 1} on && /^-- P/ && index($0, start) != 1 {exit} on' "$PREFLIGHT" \
    | grep -v '^--' > "$WORK/block.sql"
  PGOPTIONS="-c default_transaction_read_only=on" pg -f "$WORK/block.sql" 2>"$WORK/err.txt"
}
has() { if echo "$1" | grep -qE "$2"; then ok "$3"; else bad "$3" "no line matching [$2] in: $(echo "$1" | head -20)"; fi; }

[ -e "$DATA" ] && { echo "refusing: $DATA already exists"; exit 2; }
mkdir -p "$WORK"
"$PGBIN/initdb" -D "$DATA" -U postgres -A trust -E UTF8 --no-locale >/dev/null || exit 2
"$PGBIN/pg_ctl" -D "$DATA" -l "$WORK/pg.log" -o "-p $PORT -c listen_addresses=localhost" -w start >/dev/null || exit 2
trap '"$PGBIN/pg_ctl" -D "$DATA" -m fast -w stop >/dev/null' EXIT
"$PGBIN/createdb" -h localhost -p "$PORT" -U postgres "$DB" || exit 2
pg -f "$HERE/suite_rls_fixture.sql" >/dev/null || exit 2

# Ownership scenarios (fake data). Owner = daniel. The FK is dropped only to stage an orphan row.
pg >/dev/null <<'SQL' || exit 2
create schema if not exists auth;
create table auth.users (id uuid primary key default gen_random_uuid(), email text,
                         created_at timestamptz default now(), last_sign_in_at timestamptz);
insert into auth.users (email) values ('daniel.owner@example.invalid'), ('danielle.other@example.invalid'),
                                      ('ariel@example.invalid'), ('john@example.invalid');
delete from public.suite_app_current_state;
alter table public.suite_app_current_state drop constraint if exists suite_app_current_state_user_id_fkey;
insert into public.suite_users (id, external_id, email) values
  ('00000000-0000-0000-0000-0000000000d1', 'daniel', 'daniel.owner@example.invalid'),
  ('00000000-0000-0000-0000-0000000000a1', 'ariel', 'ariel@example.invalid'),
  ('00000000-0000-0000-0000-0000000000c1', 'coakley11', ''),
  ('00000000-0000-0000-0000-0000000000e1', 'john', 'john@example.invalid');
insert into public.suite_app_current_state (app, user_id, metrics) values
  ('baseball', '00000000-0000-0000-0000-0000000000d1',
     '{"full_session": {"secret_board": "CONTENT-MUST-NOT-PRINT", "live_draft_state": {"owner_external_id": "daniel", "owner_workspace_id": "coakley11"}}}'),
  ('investment', '00000000-0000-0000-0000-0000000000e1', '{}'),
  ('music', '00000000-0000-0000-0000-0000000000d1',
     '{"full_session": {"live_draft_room": {"owner_external_id": "john"}}}'),
  ('baseball__ariel', '00000000-0000-0000-0000-0000000000d1', '{}'),
  ('baseball__coakley11', '00000000-0000-0000-0000-0000000000c1', '{"full_session": {}}'),
  ('baseball__john', '00000000-0000-0000-0000-0000000000d1', '{}'),
  ('baseball__health_probe', '00000000-0000-0000-0000-0000000000e1', '{}'),
  ('nba', null, '{}'),
  ('future_lens', '00000000-0000-0000-0000-0000000000ff', '{}');
insert into public.suite_activity_events (app, event, user_id) values
  ('baseball', 'save', '00000000-0000-0000-0000-0000000000d1'),
  ('baseball', 'save', '00000000-0000-0000-0000-0000000000e1'),
  ('baseball', 'save', null);
insert into public.suite_resume_items (app, item_key, title, user_id) values
  ('baseball__coakley11', 'k1', 'Continue', '00000000-0000-0000-0000-0000000000c1');
SQL

ALL=""
echo "P1-P3, P11: schema facts"
out=$(block "-- P1-P3, P11.") && ok "runs read-only" || bad "runs read-only" "$(cat "$WORK/err.txt")"
ALL="$ALL$out"
has "$out" "PRIMARY KEY \(app\)" "primary key reported"
has "$out" "\|9\|1\|1\|" "9 rows, 1 with no owner, 1 orphan"
has "$out" "service_role=true" "service_role bypass reported"

echo "P4-P7, P14: per-row ownership flags"
out=$(block "-- P4-P7, P14.") && ok "runs read-only" || bad "runs read-only" "$(cat "$WORK/err.txt")"
ALL="$ALL$out"
has "$out" "^baseball\|\(unscoped\)\|daniel\|daniel\|.*\|ok$" "owner's unscoped row with the owner's stamp: ok"
has "$out" "^investment\|\(unscoped\)\|acct_[0-9a-f]{6}\|.*P6 KEY_OWNER_MISMATCH$" "owner's unscoped key held by another account: P6"
has "$out" "^music\|\(unscoped\)\|daniel\|acct_[0-9a-f]{6}\|.*P14 DRAFT_STAMP_MISMATCH$" "owner's row holding another account's draft: P14"
has "$out" "^baseball__ariel\|ariel\|daniel\|.*PRESET_HELD_BY_OWNER$" "preset held by the owner"
has "$out" "^baseball__coakley11\|acct_[0-9a-f]{6}\|acct_[0-9a-f]{6}\|.*\|ok$" "account's own scoped key: ok"
has "$out" "^baseball__john\|acct_[0-9a-f]{6}\|daniel\|.*P6 KEY_OWNER_MISMATCH$" "another account's scoped key held by the owner: P6"
has "$out" "^baseball__health_probe\|health_probe\|.*SHARED_KEY$" "health probe: SHARED_KEY"
has "$out" "^nba\|\(unscoped\)\|\(no owner\)\|.*P4 NULL_OWNER$" "ownerless row: P4"
has "$out" "^future_lens\|\(unscoped\)\|\(orphan id\)\|.*ORPHAN_OWNER$" "owner id with no profile: ORPHAN_OWNER"
first=$(echo "$out" | head -1 | cut -d'|' -f2)
[ "$first" = "(unscoped)" ] && ok "unscoped rows first (P7)" || bad "unscoped rows first (P7)" "$first"

echo "P13: other writers under the same key"
out=$(block "-- P13.") && ok "runs read-only" || bad "runs read-only" "$(cat "$WORK/err.txt")"
ALL="$ALL$out"
has "$out" "^baseball\|daniel\|acct_[0-9a-f]{6}\|f\|activity_events\|1\|" "another account's events under the owner's key"
has "$out" "^baseball\|daniel\|daniel\|t\|activity_events\|1\|" "the owner's own events"
has "$out" "^baseball\|daniel\|\(no user\)\|f\|activity_events\|1\|" "events with no user"
has "$out" "^baseball__coakley11\|acct_[0-9a-f]{6}\|acct_[0-9a-f]{6}\|t\|resume_items\|1\|" "resume items by the row's owner"

echo "P8: identities (masked)"
out=$(block "-- P8.") && ok "runs read-only" || bad "runs read-only" "$(cat "$WORK/err.txt")"
ALL="$ALL$out"
has "$out" "^auth sign-in\|d\*\*\*@example.invalid\|daniel\|daniel\|" "owner's sign-in maps to the owner's profile"
has "$out" "^auth sign-in\|d\*\*\*@example.invalid\|daniel\|\(no profile records this email\)\|" "another 'daniel' email the legacy rule maps onto the owner"
has "$out" "^auth sign-in\|a\*\*\*@example.invalid\|ariel\|ariel\|" "ariel sign-in"
has "$out" "^suite profile\|\(no email\)\|\|acct_[0-9a-f]{6}\|" "profile with no email"

echo "P9-P10: access on every suite table"
out=$(block "-- P9-P10.") && ok "runs read-only" || bad "runs read-only" "$(cat "$WORK/err.txt")"
ALL="$ALL$out"
has "$out" "^suite_saved_items\|f\|f\|0\|t\|t\|t\|t\|t$" "exposed table as found in the fixture"
first=$(echo "$out" | head -1 | cut -d'|' -f2)
[ "$first" = "f" ] && ok "exposed tables first" || bad "exposed tables first" "$first"

echo "P12: per-row fingerprint"
out=$(block "-- P12.") && ok "runs read-only" || bad "runs read-only" "$(cat "$WORK/err.txt")"
ALL="$ALL$out"
c6=$(pg -c "select md5(coalesce(string_agg(md5(x::text), ',' order by md5(x::text)), '')) from public.suite_app_current_state x")
[ "$(echo "$out" | head -1 | cut -d'|' -f6)" = "$c6" ] && ok "table_fp equals the C6 fingerprint" || bad "table_fp equals the C6 fingerprint"
[ "$(echo "$out" | wc -l)" -eq 9 ] && ok "one line per row" || bad "one line per row"

echo "P1b: schema definitions"
out=$(block "-- P1b.") && ok "runs read-only" || bad "runs read-only" "$(cat "$WORK/err.txt")"
ALL="$ALL$out"
has "$out" "^version\|\|[0-9]+" "version"
has "$out" "^column\|user_id\|uuid nullable" "user_id is nullable"
has "$out" "^column\|app\|text not null" "app column"
has "$out" "^constraint\|suite_app_current_state_pkey\|PRIMARY KEY \(app\)" "primary key definition"
has "$out" "^index\|suite_app_current_state_pkey\|CREATE UNIQUE INDEX" "index definition"
if echo "$out" | grep -q "^trigger"; then bad "no trigger on the fixture"; else ok "no trigger on the fixture (none listed)"; fi

echo "P15: live-draft owner stamps"
out=$(block "-- P15.") && ok "runs read-only" || bad "runs read-only" "$(cat "$WORK/err.txt")"
ALL="$ALL$out"
has "$out" "^baseball\|daniel\|t\|f\|daniel\|acct_[0-9a-f]{6}\|same\|" "stamp names the owner: same"
has "$out" "^music\|daniel\|f\|t\|acct_[0-9a-f]{6}\|\|DIFFERENT\|" "stamp names another profile: DIFFERENT"
has "$out" "^nba\|\(no owner\)\|f\|f\|\|\|\|" "no live draft: empty stamps"
[ "$(echo "$out" | wc -l)" -eq 9 ] && ok "one line per row" || bad "one line per row"

echo "Nothing sensitive in any output"
if echo "$ALL" | grep -qiE "[0-9a-f]{8}-[0-9a-f]{4}-"; then bad "no user id"; else ok "no user id"; fi
if echo "$ALL" | grep -qE "[a-z.]+@example"; then bad "no full email"; else ok "no full email"; fi
if echo "$ALL" | grep -qE "CONTENT-MUST-NOT-PRINT|secret_board"; then bad "no row content"; else ok "no row content"; fi
if echo "$ALL" | grep -qE "\|(john|coakley11)\|"; then bad "non-preset profiles pseudonymised"; else ok "non-preset profiles pseudonymised"; fi

echo "Whole file is read-only"
if PGOPTIONS="-c default_transaction_read_only=on" pg -f "$PREFLIGHT" >/dev/null 2>"$WORK/err.txt"; then ok "all blocks run read-only"
else bad "all blocks run read-only" "$(cat "$WORK/err.txt")"; fi

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
