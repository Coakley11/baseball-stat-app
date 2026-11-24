#!/usr/bin/env bash
# Tests suite_sid_prod_revocation_GUARDED_20261124.sql and suite_sid_owner_mapping_READONLY.sql on a throwaway
# local cluster (suite_rls_fixture.sql + Supabase-like auth tables). Fake data only. The pinned production
# counts are substituted with this fixture's counts.
#   scripts/sql_tests/suite_sid_revocation_20261124_local_test.sh <empty scratch dir> [pg bin dir] [port]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SQL="$HERE/../../docs/sql"
REV="$SQL/suite_sid_prod_revocation_GUARDED_20261124.sql"
MAP="$SQL/suite_sid_owner_mapping_READONLY.sql"
WORK="${1:?usage: $0 <scratch dir> [pg bin dir] [port]}"
PGBIN="${2:-/c/Program Files/PostgreSQL/17/bin}"
PORT="${3:-55443}"
DATA="$WORK/pgdata"; DB=suite; PASS=0; FAIL=0
pg() { "$PGBIN/psql" -X -q -tA -v ON_ERROR_STOP=1 -h localhost -p "$PORT" -U postgres -d "$DB" "$@"; }
ok()  { PASS=$((PASS + 1)); echo "  ok    $1"; }
bad() { FAIL=$((FAIL + 1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && echo "        $2"; }
equals() { if [ "$1" = "$2" ]; then ok "$3"; else bad "$3" "expected [$2] got [$1]"; fi; }
q() { pg -c "$1" 2>&1; }
fp_all() { q "select md5(coalesce(string_agg(md5(x::text), ',' order by x.id), '')) from public.suite_saved_items x"; }
fp_other() { q "select md5(coalesce(string_agg(md5(x::text), ',' order by x.id), '')) from public.suite_saved_items x where not (app = '_auth_browser' and item_type = 'browser_session')"; }
rev_with() {  # rows other users
  sed -e "s/expected_rows       constant int := 1485;/expected_rows       constant int := $1;/" \
      -e "s/expected_other      constant int := 1308;/expected_other      constant int := $2;/" \
      -e "s/expected_auth_users constant int := 3;/expected_auth_users constant int := $3;/" "$REV" > "$WORK/rev.sql"
  pg -f "$WORK/rev.sql" > "$WORK/rev_out.txt" 2>&1
}

[ -e "$DATA" ] && { echo "refusing: $DATA already exists"; exit 2; }
mkdir -p "$WORK"
"$PGBIN/initdb" -D "$DATA" -U postgres -A trust -E UTF8 --no-locale >/dev/null || exit 2
"$PGBIN/pg_ctl" -D "$DATA" -l "$WORK/pg.log" -o "-p $PORT -c listen_addresses=localhost" -w start >/dev/null || exit 2
trap '"$PGBIN/pg_ctl" -D "$DATA" -m fast -w stop >/dev/null' EXIT
"$PGBIN/createdb" -h localhost -p "$PORT" -U postgres "$DB" || exit 2
pg -f "$HERE/suite_rls_fixture.sql" >/dev/null || exit 2
pg >/dev/null <<'SQL'
create schema auth;
create table auth.users (id uuid primary key, email text, created_at timestamptz default now());
insert into auth.users values ('00000000-0000-0000-0000-0000000000a1', 'a@example.invalid', now() - interval '3 days'),
                              ('00000000-0000-0000-0000-0000000000b1', 'b@example.invalid', now() - interval '2 days');
-- profiles: one with A's email, one guest workspace without email holding B's token
insert into public.suite_users (id, external_id, email) values
  ('00000000-0000-0000-0000-0000000000f1', 'profile-a', 'a@example.invalid'),
  ('00000000-0000-0000-0000-0000000000f2', 'guest_ws_1', '');
-- fake JWTs: header.base64url({"sub": ...}).sig
insert into public.suite_saved_items (user_id, app, item_type, item_key, title, payload, valid) values
  ('00000000-0000-0000-0000-0000000000f1', '_auth_browser', 'browser_session', 'sid-f1-a', 'session',
   jsonb_build_object('access_token', 'eyJhbGciOiJIUzI1NiJ9.' || rtrim(translate(encode(convert_to('{"sub":"00000000-0000-0000-0000-0000000000a1"}', 'UTF8'), 'base64'), '+/', '-_'), '=') || '.sig', 'refresh_token', 'fake-r1'), true),
  ('00000000-0000-0000-0000-0000000000f2', '_auth_browser', 'browser_session', 'sid-f2-b', 'session',
   jsonb_build_object('access_token', 'eyJhbGciOiJIUzI1NiJ9.' || rtrim(translate(encode(convert_to('{"sub":"00000000-0000-0000-0000-0000000000b1"}', 'UTF8'), 'base64'), '+/', '-_'), '=') || '.sig', 'refresh_token', 'fake-r2'), false),
  ('00000000-0000-0000-0000-0000000000f2', '_auth_browser', 'browser_session', 'sid-f2-x', 'session',
   '{"access_token": "not-a-jwt", "refresh_token": "fake-r3"}', true);
SQL
N_BRIDGE=$(q "select count(*) from public.suite_saved_items where app = '_auth_browser' and item_type = 'browser_session'")
N_OTHER=$(q "select count(*) from public.suite_saved_items where not (app = '_auth_browser' and item_type = 'browser_session')")
N_VALID=$(q "select count(*) from public.suite_saved_items where app = '_auth_browser' and item_type = 'browser_session' and valid")
echo "fixture: $N_BRIDGE browser-session rows, $N_OTHER other saved items, 2 Auth users"

echo "Owner mapping (read-only)"
if PGOPTIONS="-c default_transaction_read_only=on" pg -F '|' -f "$MAP" > "$WORK/map.txt" 2>&1; then ok "runs inside a read-only transaction"; else bad "runs read-only" "$(cat "$WORK/map.txt")"; fi
grep -qiE "example|0000-0000|fake-|profile-a|guest_ws" "$WORK/map.txt" && bad "prints no email, id, token or external id" "$(cat "$WORK/map.txt")" || ok "prints no email, id, token or external id"
grep -q "profile email = an Auth account|named profile|token account #1" "$WORK/map.txt" && ok "maps A's profile to Auth account #1 via the token" || bad "A mapping" "$(cat "$WORK/map.txt")"
grep -q "profile has no email|guest workspace|token account #2, token unreadable" "$WORK/map.txt" && ok "shows B's token stored under a guest profile without email" || bad "B mapping" "$(cat "$WORK/map.txt")"

echo "Guarded revocation refuses and changes nothing"
before=$(fp_all)
rev_with 1485 1308 3; grep -q "refused: 2 Auth users, expected 3" "$WORK/rev_out.txt" && ok "refuses on the wrong project (Auth user count)" || bad "wrong project" "$(cat "$WORK/rev_out.txt")"
equals "$(fp_all)" "$before" "  nothing changed"
rev_with 40 "$N_OTHER" 2; grep -q "refused: $N_BRIDGE browser-session rows, expected 40" "$WORK/rev_out.txt" && ok "refuses on a row-count mismatch" || bad "row mismatch" "$(cat "$WORK/rev_out.txt")"
equals "$(fp_all)" "$before" "  nothing changed"
rev_with "$N_BRIDGE" 900 2; grep -q "other saved items, expected about 900" "$WORK/rev_out.txt" && ok "refuses when other saved items are far from the preflight" || bad "other drift" "$(cat "$WORK/rev_out.txt")"
equals "$(fp_all)" "$before" "  nothing changed"
q "create function public._qa_touch() returns trigger language plpgsql as \$\$ begin update public.suite_saved_items set title = title || '!' where id = (select min(id) from public.suite_saved_items where app <> '_auth_browser'); return new; end \$\$; create trigger _qa_touch after update on public.suite_saved_items for each row when (new.app = '_auth_browser') execute function public._qa_touch();" >/dev/null
rev_with "$N_BRIDGE" "$N_OTHER" 2; grep -q "rolled back: other saved items changed" "$WORK/rev_out.txt" && ok "rolls back when another saved item changes" || bad "fingerprint rollback" "$(cat "$WORK/rev_out.txt")"
equals "$(fp_all)" "$before" "  nothing changed (rolled back)"
q "drop trigger _qa_touch on public.suite_saved_items; drop function public._qa_touch();" >/dev/null
q "create function public._qa_keep() returns trigger language plpgsql as \$\$ begin new.payload := new.payload || '{\"refresh_token\":\"x\"}'; return new; end \$\$; create trigger _qa_keep before update on public.suite_saved_items for each row execute function public._qa_keep();" >/dev/null
rev_with "$N_BRIDGE" "$N_OTHER" 2; grep -q "rolled back: .* still valid or holding a token" "$WORK/rev_out.txt" && ok "rolls back when a token survives" || bad "token rollback" "$(cat "$WORK/rev_out.txt")"
equals "$(fp_all)" "$before" "  nothing changed (rolled back)"
q "drop trigger _qa_keep on public.suite_saved_items; drop function public._qa_keep();" >/dev/null

echo "Guarded revocation applies"
other=$(fp_other)
rev_with "$N_BRIDGE" "$N_OTHER" 2; grep -q "OK: revoked $N_BRIDGE browser-session rows ($N_VALID had been valid); $N_OTHER other saved items unchanged" "$WORK/rev_out.txt" && ok "revokes every browser-session row" || bad "applies" "$(cat "$WORK/rev_out.txt")"
grep -q "^$N_BRIDGE|0|0|$N_OTHER$" "$WORK/rev_out.txt" && ok "verify query: all rows invalid, no tokens, other items counted" || bad "verify query" "$(tail -3 "$WORK/rev_out.txt")"
equals "$(fp_other)" "$other" "other saved items byte-for-byte unchanged"
equals "$(q "select count(*) from public.suite_saved_items where app = '_auth_browser' and payload->>'revoked' = 'true'")" "$N_BRIDGE" "rows kept for the audit trail, marked revoked"
rev_with "$N_BRIDGE" "$N_OTHER" 2; grep -q "OK: revoked $N_BRIDGE browser-session rows (0 had been valid)" "$WORK/rev_out.txt" && ok "running it twice is harmless" || bad "idempotent" "$(cat "$WORK/rev_out.txt")"

echo; echo "passed $PASS, failed $FAIL"
[ "$FAIL" -eq 0 ]
