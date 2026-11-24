#!/usr/bin/env bash
# Tests suite_auth_signout_readiness_READONLY.sql and suite_auth_global_signout_GUARDED_20261124.sql (pinned) against a throwaway
# local PostgreSQL cluster (suite_rls_fixture.sql + Supabase-like auth tables). Fake data only.
#   scripts/sql_tests/suite_auth_signout_local_test.sh <empty scratch dir> [pg bin dir] [port]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SQL="$HERE/../../docs/sql"
RDY="$SQL/suite_auth_signout_readiness_READONLY.sql"
OUT="$SQL/suite_auth_global_signout_GUARDED_20261124.sql"
WORK="${1:?usage: $0 <scratch dir> [pg bin dir] [port]}"
PGBIN="${2:-/c/Program Files/PostgreSQL/17/bin}"
PORT="${3:-55451}"
DATA="$WORK/pgdata"; DB=suite; PASS=0; FAIL=0
pg() { "$PGBIN/psql" -X -q -tA -v ON_ERROR_STOP=1 -h localhost -p "$PORT" -U postgres -d "$DB" "$@"; }
ok()  { PASS=$((PASS + 1)); echo "  ok    $1"; }
bad() { FAIL=$((FAIL + 1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && echo "        $2"; }
equals() { if [ "$1" = "$2" ]; then ok "$3"; else bad "$3" "expected [$2] got [$1]"; fi; }
q() { pg -c "$1" 2>&1; }
fp_public() { q "select md5(string_agg(t.tablename || ':' || (xpath('/row/c/text()', query_to_xml(format('select md5(coalesce(string_agg(md5(x::text), '','' order by md5(x::text)), '''')) as c from public.%I x', t.tablename), false, true, '')))[1]::text, ';' order by t.tablename)) from pg_tables t where t.schemaname = 'public'"; }
fp_auth()   { q "select (select count(*) from auth.users) || '/' || (select count(*) from auth.identities) || '/' || (select count(*) from auth.sessions) || '/' || (select count(*) from auth.refresh_tokens where not revoked) || '/' || (select count(*) from auth.mfa_amr_claims)"; }
run_with() {  # sessions [users identities public-tables]
  sed -e "s/expected_sessions   constant int := 18;/expected_sessions   constant int := $1;/"       -e "s/expected_users      constant int := 4;/expected_users      constant int := ${2:-2};/"       -e "s/expected_identities constant int := 4;/expected_identities constant int := ${3:-2};/"       -e "s/expected_pub_tables constant int := 9;/expected_pub_tables constant int := ${4:-$NPUB};/"       -e "s/4 users, 4 identities/N users, N identities/" -e "s/all 9 public tables/all public tables/" "$OUT" > "$WORK/out.sql"
  pg -f "$WORK/out.sql" > "$WORK/out.txt" 2>&1
}
rdy_val()  { pg -f "$RDY" | grep -F "|$1|" | head -1 | awk -F'|' '{print $3}'; }

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
create table auth.identities (id uuid primary key, user_id uuid references auth.users (id) on delete cascade, provider text not null default 'email');
create table auth.mfa_factors (id uuid primary key, user_id uuid references auth.users (id) on delete cascade, factor_type text, status text);
create table auth.sessions (id uuid primary key, user_id uuid references auth.users (id) on delete cascade,
                            created_at timestamptz default now(), not_after timestamptz);
create table auth.refresh_tokens (id bigserial primary key, session_id uuid references auth.sessions (id) on delete cascade,
                                  revoked boolean default false, created_at timestamptz default now(), updated_at timestamptz);
create table auth.mfa_amr_claims (id uuid primary key, session_id uuid references auth.sessions (id) on delete cascade);
insert into auth.users values ('00000000-0000-0000-0000-0000000000a1', 'a@example.invalid'),
                              ('00000000-0000-0000-0000-0000000000b1', 'b@example.invalid');
insert into auth.identities values ('00000000-0000-0000-0000-0000000001a1', '00000000-0000-0000-0000-0000000000a1', 'email'),
                                   ('00000000-0000-0000-0000-0000000001b1', '00000000-0000-0000-0000-0000000000b1', 'email');
insert into auth.mfa_factors values ('00000000-0000-0000-0000-0000000003a1', '00000000-0000-0000-0000-0000000000a1', 'totp', 'verified');
insert into auth.sessions (id, user_id, created_at) values
  ('00000000-0000-0000-0000-00000000a001', '00000000-0000-0000-0000-0000000000a1', now() - interval '3 days'),
  ('00000000-0000-0000-0000-00000000a002', '00000000-0000-0000-0000-0000000000a1', now() - interval '2 hours'),
  ('00000000-0000-0000-0000-00000000b001', '00000000-0000-0000-0000-0000000000b1', null);
insert into auth.refresh_tokens (session_id, revoked, created_at) values
  ('00000000-0000-0000-0000-00000000a001', false, now() - interval '3 days'),
  ('00000000-0000-0000-0000-00000000a001', true,  now() - interval '3 days'),
  ('00000000-0000-0000-0000-00000000a002', false, now() - interval '2 hours'),
  ('00000000-0000-0000-0000-00000000b001', false, now() - interval '1 day'),
  (null, false, now() - interval '400 days');
insert into auth.mfa_amr_claims values ('00000000-0000-0000-0000-0000000002a1', '00000000-0000-0000-0000-00000000a002');
SQL

NPUB=$(q "select count(*) from pg_tables where schemaname = 'public'")
echo "Readiness (read-only)"
if PGOPTIONS="-c default_transaction_read_only=on" pg -f "$RDY" > "$WORK/rdy.txt" 2>&1; then ok "runs inside a read-only transaction"; else bad "runs read-only" "$(cat "$WORK/rdy.txt")"; fi
grep -qi "@example" "$WORK/rdy.txt" && bad "returns no email" || ok "returns no email"
equals "$(rdy_val 'Auth sessions to sign out')" "3" "counts sessions"
equals "$(rdy_val 'unrevoked refresh tokens')" "4" "counts unrevoked refresh tokens"
equals "$(rdy_val 'unrevoked refresh tokens without a session (legacy)')" "1" "counts legacy tokens"
equals "$(rdy_val 'may DELETE auth.sessions')" "true" "reports the delete privilege"
grep -q "on delete of a session: auth.refresh_tokens|CASCADE" "$WORK/rdy.txt" && ok "reports cascading references" || bad "reports references" "$(grep references "$WORK/rdy.txt")"

echo "Guarded sign-out refuses and changes nothing"
pub=$(fp_public); auth=$(fp_auth)
run_with 3 4; grep -q "refused: 2 Auth users, expected 4" "$WORK/out.txt" && ok "refuses when the account count differs (e.g. a new sign-up)" || bad "users pin" "$(cat "$WORK/out.txt")"
run_with 3 2 2 99; grep -q "refused: .* public tables, expected 99" "$WORK/out.txt" && ok "refuses when the public table count differs" || bad "tables pin" "$(cat "$WORK/out.txt")"
equals "$(fp_auth)" "$auth" "  Auth unchanged"
run_with 40; grep -q "3 sessions in scope, expected 40" "$WORK/out.txt" && ok "refuses on a count mismatch" || bad "refuses on mismatch" "$(cat "$WORK/out.txt")"
equals "$(fp_auth)" "$auth" "  Auth unchanged"
# a verification failure after the deletes must roll everything back (sessions silently survive the delete)
q "create function auth._qa_keep() returns trigger language plpgsql as \$\$ begin return null; end \$\$; create trigger _qa_keep before delete on auth.sessions for each row execute function auth._qa_keep();" >/dev/null
run_with 3; grep -qE "rolled back: (sessions from before the cutoff remain|deleted 0 sessions, scope was 3)" "$WORK/out.txt" && ok "rolls back when sessions survive the delete" || bad "rolls back on failed verification" "$(cat "$WORK/out.txt")"
equals "$(fp_auth)" "$auth" "  Auth unchanged (tokens and claims restored)"
q "drop trigger _qa_keep on auth.sessions; drop function auth._qa_keep();" >/dev/null
# application data changing during the run must roll back too
q "create function auth._qa_touch() returns trigger language plpgsql as \$\$ begin update public.suite_saved_items set title = title || '!' where id = (select min(id) from public.suite_saved_items); return old; end \$\$; create trigger _qa_touch before delete on auth.sessions for each row execute function auth._qa_touch();" >/dev/null
run_with 3; grep -q "rolled back: application data changed" "$WORK/out.txt" && ok "rolls back when application data changes" || bad "rolls back on data change" "$(cat "$WORK/out.txt")"
equals "$(fp_public)" "$pub" "  application data unchanged"
q "drop trigger _qa_touch on auth.sessions; drop function auth._qa_touch();" >/dev/null

echo "Guarded sign-out applies with the right count"
run_with 3; grep -q "OK: signed out 3 sessions; deleted 4 refresh tokens (3 were still usable), 1 MFA session claims; 1 legacy tokens revoked" "$WORK/out.txt" && ok "signs out every session" || bad "applies" "$(cat "$WORK/out.txt")"
equals "$(q 'select count(*) from auth.sessions')" "0" "no session left"
equals "$(q 'select count(*) from auth.refresh_tokens where not revoked')" "0" "no usable refresh token left"
equals "$(q 'select count(*) from auth.users')/$(q 'select count(*) from auth.identities')/$(q 'select count(*) from auth.mfa_factors')" "2/2/1" "users, identities and the registered MFA factor kept"
equals "$(fp_public)" "$pub" "every public table unchanged (saved items, settings, leagues, drafts, subscriptions...)"
q "insert into auth.sessions (id, user_id) values ('00000000-0000-0000-0000-00000000a003', '00000000-0000-0000-0000-0000000000a1')" >/dev/null
equals "$(q 'select count(*) from auth.sessions')" "1" "signing in again works afterwards (new session accepted)"

echo "A non-cascading reference cannot block or orphan it"
q "alter table auth.refresh_tokens drop constraint refresh_tokens_session_id_fkey; alter table auth.refresh_tokens add constraint refresh_tokens_session_id_fkey foreign key (session_id) references auth.sessions (id);
   insert into auth.refresh_tokens (session_id, created_at) values ('00000000-0000-0000-0000-00000000a003', now() - interval '1 minute');" >/dev/null
run_with 1; grep -q "OK: signed out 1 sessions; deleted 1 refresh tokens" "$WORK/out.txt" && ok "deletes tokens explicitly before sessions" || bad "non-cascading FK" "$(cat "$WORK/out.txt")"
equals "$(fp_public)" "$pub" "  application data unchanged"

echo "Concurrent save during the run waits instead of causing a false rollback"
q "insert into auth.sessions (id, user_id, created_at) values ('00000000-0000-0000-0000-00000000a009', '00000000-0000-0000-0000-0000000000a1', now() - interval '1 hour')" >/dev/null
( "$PGBIN/psql" -X -q -h localhost -p "$PORT" -U postgres -d "$DB" -c "select pg_sleep(1); update public.suite_saved_items set title = title || '+' where id = (select min(id) from public.suite_saved_items);" >/dev/null 2>&1 & )
run_with 1; grep -q "OK: signed out 1 sessions" "$WORK/out.txt" && ok "completes while a user save is queued" || bad "concurrent save" "$(cat "$WORK/out.txt")"
for i in $(seq 1 30); do [ "$(q "select count(*) from public.suite_saved_items where title like '%+'")" = "1" ] && break; q "select pg_sleep(0.3)" >/dev/null; done
equals "$(q "select count(*) from public.suite_saved_items where title like '%+'")" "1" "  the queued save then succeeds"

echo; echo "passed $PASS, failed $FAIL"
[ "$FAIL" -eq 0 ]
