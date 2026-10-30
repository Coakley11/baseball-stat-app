# Suite tables open to the anon role: containment

Status: Step 1 is ready for the owner's authorization. It has been tested locally only, and nothing has been run on any Supabase project. The token incident response is separate: `SUITE_AUTH_TOKEN_INCIDENT_RESPONSE.md`.

## Confirmed exposure (owner's read-only inspection, 2026-10-30)

| Table | RLS | Policies | anon grants | Exposed to the anon key |
|---|---|---|---|---|
| `suite_users` | **off** | 0 | SELECT, INSERT, UPDATE, DELETE | **Yes** |
| `suite_saved_items` | **off** | 0 | SELECT, INSERT, UPDATE, DELETE | **Yes**, including every stored `access_token` / `refresh_token` |
| `suite_user_settings` | **off** | 0 | SELECT, INSERT, UPDATE, DELETE | **Yes** |
| `suite_activity_events`, `suite_app_current_state`, `suite_resume_items` | on | 0 | granted | No: RLS with no policy denies every row |

- **Who uses these tables.** Every suite app reaches them only server-side, with the service-role key. No browser code, Edge Function, view, RPC or anon-key client in the seven suite repos touches them.
- **The anon key with a user token** is used only for billing tables.
- **History.** No Supabase key is in the history of any of the seven repos, all of which are public on GitHub.

## Step 1: the exact SQL

The file is `docs/sql/suite_rls_containment_step1_DRAFT.sql`. It is **one statement** (a `DO` block), so it is atomic in any client, including the Supabase SQL editor: either all of it applies, or nothing does.

**The change itself:**
```sql
alter table public.suite_users enable row level security;
alter table public.suite_saved_items enable row level security;
alter table public.suite_user_settings enable row level security;
revoke all on table public.suite_users, public.suite_saved_items, public.suite_user_settings
  from anon, authenticated;
-- the identity sequence behind suite_saved_items.id, resolved with pg_get_serial_sequence():
revoke all on sequence <suite_saved_items id sequence> from anon, authenticated;
```

**Checks it makes first.** Each failure aborts with `ABORTED, nothing changed: <reason>`.

| # | Check | Why |
|---|---|---|
| 1 | `service_role` bypasses RLS and holds SELECT, INSERT, UPDATE and DELETE on all three tables | The apps keep working |
| 2 | No grant to **PUBLIC** on the tables or the sequence | Every role inherits a PUBLIC grant; a revoke from anon wouldn't remove it |
| 3 | anon / authenticated don't belong to any role with access to the tables | Inherited access would survive the revoke |
| 4 | No **view** over the tables that anon / authenticated can use | An owner's view reads past both the grants and RLS |
| 5 | No **SECURITY DEFINER function** naming the tables that anon / authenticated can call | It runs as its owner, past both |

**Proof it makes afterwards.** Any failure undoes the change.
- RLS is on for all three tables.
- anon and authenticated hold **no** table privilege (SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER), **no** column privilege, and **no** sequence privilege.
- **Every service_role grant on every suite table and sequence is identical** to the snapshot taken before the change.

**Other properties.**
- It sets a 5-second lock timeout. If a long query holds a table, it gives up and changes nothing.
- It reads no row content, changes or deletes no row, and does not touch the `auth` schema.
- On success it prints: `Step 1 applied: RLS on and anon/authenticated access removed …; service_role grants unchanged.`

**Limits of the checks.**
- Check 5 matches function bodies by table name, so a function that builds the table name dynamically wouldn't be found. Preflight C3b lists every function for review.
- Realtime and GraphQL are covered by the grants and RLS themselves: with both in place, neither serves these rows to anon.

## Essential preflight before execution (`suite_rls_containment_preflight.sql`, read-only)

Run the whole file. It returns catalog facts, counts and hashes only, never row content. Check these:

| Result | What must be true | Save it? |
|---|---|---|
| **C1** | For the three tables: `rls_enabled = false`, and anon / authenticated show `true` (confirms the target state). **service_role shows `true` for all four privileges on all six tables.** | Yes |
| **C1b** | `owner`, `grantor` and `running_as` are the same role, normally `postgres`. If a grantor differs, Step 1 still fails safe, but tell me before running so the revoke can be adjusted. | Yes |
| **C2** | It lists `grant …` lines for anon / authenticated on the three tables and the sequence, and three `alter table … disable row level security;` lines. **This is the exact rollback.** | **Yes, verbatim** |
| **C6** | A count and fingerprint per table. | **Yes**, to compare right after |
| C7 (1 minute) | Recent `last_state_write` / `last_event_write` for each live app. Those tables already refuse the anon key, so recent writes prove the app uses the service-role key. | Optional |

C3 and C4 are informational. Step 1 enforces the view, function, PUBLIC and membership checks itself.

## After execution: exact verification steps

1. **Read the result.**
   - `Step 1 applied: …` means it worked.
   - `ABORTED, nothing changed: …` means nothing changed. Send me the reason.
2. **Run `suite_rls_containment_verify.sql`** (read-only):
   - V1: `rls_enabled = true` for the three tables.
   - V2: for those three, anon and authenticated show `false` in every column, and service_role shows `true` in every column.
   - V3: `service_role | true`.
3. **Run preflight C6 again** and compare with the saved output.
   - `suite_users` should be identical unless someone signed up in between.
   - `suite_saved_items` and `suite_user_settings` can differ only by the apps' own writes since then (for example, a sign-in rewrites its browser session row). Compare straight away.
4. **From outside, with the anon key in an environment variable** (never pasted into a command or report), each of the three tables returns HTTP **401** with code `42501`:
   ```
   curl -s -o /dev/null -w "%{http_code}\n" -H "apikey: $SUPABASE_ANON_KEY" \
     -H "Authorization: Bearer $SUPABASE_ANON_KEY" "$SUPABASE_URL/rest/v1/suite_saved_items?select=id&limit=1"
   ```
5. **In each live suite app:** sign in (this writes the browser session row), load a page that reads account settings, open a saved item or Continue card, then sign out and back in on a second browser.
6. **Dashboard → Advisors → Security.** The "RLS disabled in public" findings for the three tables are gone.

## Rollback

- **How.** Run the saved C2 output, verbatim, in one transaction. Locally it restores every role's privileges and the RLS flags exactly, and changes no row.
- **Fallback.** `docs/sql/suite_rls_containment_rollback_DRAFT.sql` matches the inspection as reported.
- **Rolling back re-opens the exposure,** stored sign-in tokens included. Use it only if a legitimate client breaks.

## Step 2 (separate approval)

`docs/sql/suite_rls_containment_step2_DRAFT.sql` removes the unused anon / authenticated grants on the other three tables and their sequences. RLS already blocks those roles there, so this is defense in depth only.

## Local test

`scripts/sql_tests/suite_rls_containment_local_test.sh <empty dir>` builds a throwaway PostgreSQL 17 cluster. It has Supabase's roles (`anon`, `authenticated`, and `service_role` with BYPASSRLS), the six tables as the migrations create them, the grants and RLS state as found, and fake rows. Result: **62 passed, 0 failed.**

- **The exposure as found:** anon reads another account's stored refresh token, updates another account's settings and lists profiles.
- **Read-only scripts:** the preflight and verify files run inside read-only transactions.
- **Step 1:**
  - anon and authenticated are refused on all three tables, including insert, update and sequence `setval`;
  - no row changed;
  - every service_role grant is identical;
  - the apps' own operations still work as service_role: profile lookup and creation, token-session read, saved-item upsert, insert through the identity sequence and invalidate, settings upsert and read, state compare-and-set, event append;
  - re-running it is safe.
- **Step 2:** applies; anon is refused on the other three tables; service_role still inserts.
- **The C2 rollback:** restores privileges and RLS flags exactly and changes no row.
- **Each bypass path makes Step 1 refuse, with nothing changed:** a PUBLIC grant, an anon-readable view, an anon-callable security-definer function, a role anon belongs to, a missing service_role grant, service_role without BYPASSRLS, and a busy table (it gave up at the 5-second lock timeout).
  - The test also shows why these checks exist. After a plain revoke, anon still read through the PUBLIC grant. After RLS plus revoke, anon still read through the owner's view.
- **Not covered locally:** Supabase's managed objects and the real PostgREST and GraphQL front ends. Verification steps 4–6 cover those.

## Independence from the primary-key migration

Step 1 changes no key, no data and no service_role grant, so it can proceed now. The `suite_app_current_state` plan is unaffected.
