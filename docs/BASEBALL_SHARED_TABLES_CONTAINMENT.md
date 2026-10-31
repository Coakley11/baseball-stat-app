# Shared Baseball tables open to the anon and signed-in roles: containment

Status: **ready for the owner's approval; nothing has been run on any Supabase project.** Tested locally only (72 checks). The account-isolation migration for `suite_app_current_state` and the combined Baseball deployment stay on hold until this exposure is closed and verified.

## Confirmed exposure (owner's read-only P9–P10 run, 2026-10-30)

| Table | RLS | Policies | anon read / write | authenticated read / write | service_role |
|---|---|---|---|---|---|
| `baseball_shared_draft_rooms` | **off** | 0 | **yes / yes** | **yes / yes** | full |
| `baseball_shared_leagues` | **off** | 0 | **yes / yes** | **yes / yes** | full |

- **What this means.** Anyone holding the project's public anon key can read, change and delete every shared draft room and every shared league through the Data API, without signing in. Any signed-in user of the project has the same access.
- **What is in them.**
  - A room holds `room_code` (the code people join with), `host_user_id`, the room document (picks, participants, any invite data) and a revision.
  - A league holds the league id, the draft fingerprint, and the shared league document (`team_ownership`, `league_invites`).
- **Same pattern as the three suite tables** closed by Step 1. The cause is the repository's own SQL (`scripts/sql/baseball_shared_draft_rooms.sql`, added 2026-06-23, and `baseball_shared_leagues.sql`, added 2026-07-07): it grants `anon` SELECT and `authenticated` full access, and leaves `enable row level security` commented out as "optional when using the service_role key". Supabase's default grants on new `public` tables add the rest, which is why anon can also write.
- **Not part of the exposure.** Billing tables are in a `private` schema with RLS and no API grants (`20261008_baseball_billing_runtime.sql`). They are not affected.

## How the deployed Baseball app reaches these tables

Everything goes through one function, so removing the public grants cannot disrupt it.

| Path | Code | Credentials |
|---|---|---|
| Shared draft rooms: create, join, pick, status, host, health probe | `draft_room_supabase_store._request`, `draft_room_supabase_health` | `suite_storage_supabase._request` |
| Shared leagues: read, upsert, invites, trade sync, library and startup sync | `fantasy_shared_league_supabase_store._request` | `suite_storage_supabase._request` |

- `suite_storage_supabase._request` sends the configured `[suite_activity] supabase_key` (or `SUITE_SUPABASE_KEY`) as both `apikey` and `Authorization: Bearer`. It never forwards the signed-in user's token.
- **That key bypasses RLS.** It is the key that reads and writes `suite_app_current_state`, `suite_activity_events` and `suite_resume_items`, which have RLS on and no policies. Anon or authenticated keys are refused there, and the owner's own rows were written today (2026-10-30), so the configured key is the service role.
- **No other reader.** Across all seven suite repositories, only `baseball-stat-app` names these tables. There is no browser client, Edge Function, Realtime subscription, view or RPC in any repository. Preflight D3 checks the database for views, functions, publications and triggers the repositories could not show.
- **Comments in the repo SQL** suggest signed-in clients might read these tables directly ("add policies that allow authenticated clients"). No code does. The browser never talks to Supabase for them.
- **Shared rooms work across accounts** because the app server, holding the service role, mediates every request. Removing direct access for anon and authenticated roles removes nothing the app uses.

**Residual risk to confirm in the app, not in code:** if some deployment used the anon or a user key as its `suite_activity` key, shared rooms would stop working after containment. The app's other tables would already fail for such a key, so it is unlikely. Verification step VB5 (create a room, join from a second browser) tests it right away, and the rollback is one transaction.

## Step B: the exact SQL

`docs/sql/baseball_shared_containment_stepB_DRAFT.sql`. One statement (a `DO` block), so it is atomic in any client including the Supabase SQL editor. It changes RLS flags and privileges only. It reads no row content, changes or deletes no row, and does not touch `auth`, any other table or any service_role grant.

**The change:**
```sql
alter table public.baseball_shared_draft_rooms enable row level security;
alter table public.baseball_shared_leagues enable row level security;
revoke all on table public.baseball_shared_draft_rooms, public.baseball_shared_leagues
  from anon, authenticated;
```
With RLS on and no policy, anon and authenticated are refused; `service_role` bypasses RLS and keeps its grants. There are no sequences (text keys); the file refuses to run if one ever appears.

**Checks it makes first.** Each failure aborts with `ABORTED, nothing changed: <reason>`.

| # | Check | Why |
|---|---|---|
| 1 | `service_role` bypasses RLS and holds SELECT, INSERT, UPDATE, DELETE on both tables | The app keeps working |
| 2 | No grant to **PUBLIC** | A PUBLIC grant would survive a revoke from anon |
| 3 | anon / authenticated belong to no role with access | Inherited access would survive |
| 4 | No **view** over the tables reachable by anon / authenticated | An owner's view reads past grants and RLS |
| 5 | No **SECURITY DEFINER function** naming the tables callable by them | It runs as its owner |
| 6 | No serial / identity column | Its sequence would need revoking too |

**Proof afterwards (any failure undoes the change):** RLS is on; anon and authenticated hold no table, column privilege; every service_role grant on all suite and shared-Baseball tables is identical to the snapshot taken before. It sets a 5-second lock timeout.

## Read-only preflight (`baseball_shared_containment_preflight.sql`)

Run one block at a time (the SQL editor shows one result set). Output is safe to share: no room code, league id, invite, content, user id or email; profiles appear as labels.

| Block | Shows | Save? |
|---|---|---|
| **D1** | RLS and every privilege anon / authenticated / service_role hold on both tables | Yes |
| **D1b** | Owner, grantor, PUBLIC grants, who ran it | Yes |
| **D2** | **The exact rollback**, generated from today's ACLs | **Yes, verbatim** |
| **D3** | One row of counts: views, definer functions, PUBLIC grants, serial columns open to the API roles; functions, publications and triggers for review | Yes |
| **D4** | Row counts, date ranges, revision, JSON size, host labels, rooms whose host matches no profile, and a content fingerprint | **Yes** (compared after) |
| **D5** | Rows by month of last update beside that month's Baseball events | Yes |

Expected: D3 all zeros in its first four columns; D2 lists grants for anon and authenticated on both tables plus two `disable row level security` lines.

### Production preflight results (owner's runs, 2026-10-30)

| Block | Result |
|---|---|
| **D1** | Six rows (two tables x anon, authenticated, service_role), as expected. Both tables: `rls_enabled = false`, `rls_forced = false`, `policies = 0`. `anon`, `authenticated` and `service_role` each hold all seven checked privileges (SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER). |
| **D1b** | **Passed, 8 rows.** Both tables: `owner`, `grantor` and `running_as` are all `postgres`; grantees `anon`, `authenticated`, `postgres`, `service_role`, each with all eight PostgreSQL 17 privileges (including MAINTAIN). No PUBLIC grant, no grantor mismatch, so Step B's revoke (run as `postgres`) removes every grant anon and authenticated hold. |
| **D2** | **Passed, exactly six statements** (saved verbatim in the next section). |
| **D3** | **All seven columns 0:** `views_open_to_api_roles`, `definer_functions_open_to_api_roles`, `public_grants`, `serial_columns`, `functions_naming_tables`, `in_publications`, `user_triggers`. |

D3 passed: no view, SECURITY DEFINER function, PUBLIC grant or serial column would let anon or authenticated bypass Step B's revoke, so none of Step B's checks 2, 4, 5 or 6 will refuse on those grounds. No function names the tables, so no hidden database path to them exists. Nothing is published to Realtime, and no trigger touches them. This also supports the access audit above: the only reader is the app's service-role path.

D1 confirms the exposure exactly as P9–P10 found it (anon and signed-in users can read, write, delete and even TRUNCATE both tables) and that `service_role` holds every privilege Step B's check 1 requires. The BYPASSRLS half of check 1 and the role-membership check (3) are made by Step B itself.

Still to run: D4 (save), D5.

### Saved rollback (D2 output, production, 2026-10-30)

Generated from the live ACLs before containment. Run all six in one transaction, only if a legitimate client breaks and after approval. It reopens the exposure.

```sql
begin;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.baseball_shared_draft_rooms to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.baseball_shared_draft_rooms to authenticated;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.baseball_shared_leagues to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.baseball_shared_leagues to authenticated;
alter table public.baseball_shared_draft_rooms disable row level security;
alter table public.baseball_shared_leagues disable row level security;
commit;
```

## Post-containment verification (`baseball_shared_containment_verify.sql`)

1. **VB1:** both tables `rls_enabled = true`, not forced, 0 policies.
2. **VB2:** anon and authenticated all `false`; service_role all `true`.
3. **VB3:** rerun D4. `n` must match. The fingerprint matches unless a room or league was saved in between (`newest_update` says when).
4. **VB4:** `python -I scripts/sql_tests/anon_rest_denial_check.py` now also tests both tables. Expect `HTTP 401 code=42501` for all five tables. A 200, even with an empty array, is not a pass.
5. **VB5, in the live app:** create a shared draft room, join it from a second browser, make a pick, open a shared league and a pending invite.
6. **Dashboard → Advisors → Security:** "RLS disabled in public" findings gone.

## Rollback (`baseball_shared_containment_rollback_DRAFT.sql`)

- **Preferred:** the D2 statements, verbatim, in one transaction. Locally this restored every privilege and RLS flag exactly and changed no row.
- **Fallback if D2 was not saved:** grant all to anon and authenticated on both tables, and disable RLS.
- **Rolling back reopens the exposure.** Use it only if a legitimate client breaks.

## Can past access or modification be established?

**Short answer: partly, and reads cannot be ruled out.**

| Source | What it can show | Limit |
|---|---|---|
| **The tables (D4, D5)** | Rows with no host or a host matching no profile (what an outsider's room would look like); the last update of each row; revision counts; a JSON size outlier | Each row keeps only its last update. A read leaves no trace. A deletion leaves nothing at all. |
| **Gateway logs (`suite_rls_containment_logs_readonly.sql` L3, L4)** | Requests to the two paths by day, method, status and client tag; any browser-library client tag | Does not log the key or role, so an anon request looks like the app's own. Retention depends on the plan and is probably days, not months. The window since June 23 is likely outside it. |
| **Postgres logs** | Nothing about row reads or writes by default | Statement logging is off unless enabled |
| **Audit extension (pgaudit)** | Would list statements by role | Not enabled by default; Dashboard → Database → Extensions shows it. If absent, there is no database audit trail |
| **The repositories** | When the exposure started: the SQL was added 2026-06-23 (rooms) and 2026-07-07 (leagues). The tables cannot have been open before. | The tables may have been created later |

- **The public anon key** has been usable by anyone holding it. It is not in any repository history (checked), but it is public by design and is visible to any browser that loads a client using it. The suite apps never ship it to browsers, so exposure of the key itself is limited to people who were given it or found it in the Supabase project settings.
- **What would indicate misuse:** rooms or leagues with no recognised host, clients other than the app in L4, writes at hours with no Baseball activity (D5), revisions that jump, and the owner or other users reporting rooms that changed or vanished.
- **What this cannot show:** whether anyone merely read the data. Room codes and invite data should be treated as seen if the logs show non-app clients. Mitigation if needed is to retire open rooms and leagues and re-issue invites, which is the owner's decision and not a database change.

## Order of work after approval

1. Run D1, D1b, D2, D3, D4, D5 (read-only) and send the results. **Save D2 and D4.**
2. Review them with me: D3 non-zero in any of its first four columns means Step B refuses and the cause is dealt with first.
3. Approve the exact Step B text (re-printed in full at that point).
4. Run Step B; run VB1–VB3; run the REST check; do VB5 in the app.
5. Logs Explorer L3 and L4.

Step 2 of the suite containment (the three other tables' leftover grants) can be bundled later. It is separate, and not required for this exposure.
