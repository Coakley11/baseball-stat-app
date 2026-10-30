# Suite tables open to the anon role: containment

Status: prepared and tested locally only. Nothing has been run on any Supabase project. Each step needs the owner's approval of the exact SQL.

## Confirmed exposure (owner's read-only inspection, 2026-10-30)

| Table | RLS | Policies | anon grants | Exposed to the anon key |
|---|---|---|---|---|
| `suite_users` | **off** | 0 | SELECT, INSERT, UPDATE, DELETE | **Yes**: read, change and delete every profile |
| `suite_saved_items` | **off** | 0 | SELECT, INSERT, UPDATE, DELETE | **Yes**: read, change and delete every saved item |
| `suite_user_settings` | **off** | 0 | SELECT, INSERT, UPDATE, DELETE | **Yes**: read, change and delete every account's settings |
| `suite_activity_events` | on | 0 | granted | No: RLS with no policy denies anon every row |
| `suite_app_current_state` | on | 0 | granted | No (same) |
| `suite_resume_items` | on | 0 | granted | No (same) |

**Severity is higher than a data exposure.**
- `suite_saved_items` holds every signed-in user's Supabase `access_token` and `refresh_token` in plain text. These are the rows with `app = '_auth_browser'` and `item_type = 'browser_session'`, written by `save_browser_auth_session` / `enrich_bridge_payload` in every suite app.
- Anyone holding the anon key could read a refresh token and sign in as that user, the owner included. With anon's UPDATE and DELETE, they could also change or delete any account's settings, saved items and profile rows.
- The local fixture reproduces each of these.

**Data API exposure.**
- Tables in `public` are served by the Data API (REST, and GraphQL if `pg_graphql` is on) whenever `public` is an exposed schema, which is the default.
- Preflight C3e, or Dashboard → API settings, confirms the setting. V5 confirms it from outside with one HTTP request that returns a status code, not rows.

**Who holds the anon key.**
- Nothing in any suite repo sends it to a browser. It's used server-side only, for Supabase Auth sign-in and the billing readers' `/auth/v1/user` check.
- No Supabase key, legacy JWT or new-format, appears in the history of any of the seven repos, all of which are **public** on GitHub. (One JWT-shaped string in `baseball-ami` is a test fixture with no Supabase issuer or role, in a local stash commit.)
- The anon key is public by design, though, and is in every app's Streamlit secrets. Treat the exposure as real until the API logs (below) say otherwise for the retained period.

## Which applications are affected by containment

- **Every suite app reaches these tables only through its own server-side `suite_storage_supabase._request`**, which sends the `supabase_key` secret.
  - Apps: Command Center, Baseball, Music, Investment, NBA, Future Lens and Applied Intelligence.
  - No app sends the anon key or a user JWT to these tables. No browser code and no Edge Function in these repos touches them.
- **The anon key with a user's token** is used only for billing tables: `subscriptions` (Baseball) and `billing_entitlements` (Music). Containment doesn't touch those.
- **Repo migrations add no views, functions or RPCs over these tables.** The live database can have objects the repos don't record; preflight C3a–C3c check views, functions (and whether they are security definer), and the Realtime publication.
- **Proof each live app uses an RLS-bypassing key.** `suite_app_current_state` and `suite_activity_events` already have RLS on with no policies, so only a bypassing key can write them. Any app with recent rows there (preflight C7) doesn't depend on anon access. An app with no recent rows must be checked in the API logs before Step 1.

**Expected impact on the apps: none.**
- `service_role` bypasses RLS and keeps its own grants. The revoke names only `anon` and `authenticated`.
- Locally, every operation the apps perform on these tables still succeeds as `service_role` after containment:
  - profile lookup and creation;
  - saved-item upsert on `(user_id, app, item_type, item_key)`, insert through the identity sequence, and invalidate;
  - settings upsert and read;
  - state compare-and-set;
  - event append;
  - resume insert.

## Containment SQL (`docs/sql/suite_rls_containment_DRAFT.sql`)

**Step 1** closes the exposure: one transaction, with a 5-second lock timeout so it gives up instead of queuing.

```sql
begin;
set local lock_timeout = '5s';
alter table public.suite_users enable row level security;
alter table public.suite_saved_items enable row level security;
alter table public.suite_user_settings enable row level security;
revoke all on table public.suite_users, public.suite_saved_items, public.suite_user_settings
  from anon, authenticated;
-- plus: revoke all on suite_saved_items' identity sequence from anon, authenticated
commit;
```

- Either change alone closes anon access: RLS with no policy denies every row, and without grants the role is refused outright. Doing both means one later mistake doesn't reopen it.
- The sequence revoke stops anon from `setval()`-ing the saved-items id sequence, which would break every later insert.

**Step 2** is a separate approval and defense in depth. It revokes anon and authenticated on the other three tables and their sequences. RLS already blocks them there today.

- **No row is read, changed or deleted.**
- Locally, the per-table count and content fingerprints are identical before and after.

## Rollback

- **Preferred.** Before Step 1, run preflight C2 and save its output. It generates the exact `GRANT … ;` and `DISABLE ROW LEVEL SECURITY` statements from the live catalog ACLs. To roll back, run them in one transaction.
  - Locally this restored every role's privileges on all six tables and three sequences exactly.
  - The test caught and fixed one gap: `information_schema` doesn't report sequence SELECT/UPDATE, so C2 reads the catalog instead.
- **Fallback.** `docs/sql/suite_rls_containment_rollback_DRAFT.sql` matches the inspection as reported.
- **Rolling back re-opens the exposure,** stored sign-in tokens included. Use it only if a legitimate client breaks, and prefer fixing that client.

## Verification (`docs/sql/suite_rls_containment_verify.sql`, read-only)

| Check | Expected |
|---|---|
| V1 | RLS on for all six tables |
| V2 | anon and authenticated hold no privilege; service_role holds SELECT, INSERT, UPDATE and DELETE |
| V3 | service_role still bypasses RLS |
| V4 | Rerun preflight C6: same counts and fingerprints |
| V5 | An HTTP request with the anon key (read from an environment variable, never pasted) to each of the three tables returns 401 / code 42501 |
| V6 | In each suite app, on Dev first: sign in, load settings, open a saved item or Continue card, and sign out and back in on a second browser |

## Local test (isolated fixture)

`scripts/sql_tests/suite_rls_containment_local_test.sh <empty dir>` runs against a throwaway PostgreSQL 17 cluster started in that directory on port 55432. It uses Supabase's roles (`anon`, `authenticated`, and `service_role` with BYPASSRLS), the six tables as the migrations create them, the grants and RLS state as found, and fake rows. Result: **53 passed, 0 failed.**

- The exposure as found: anon reads another account's stored refresh token, updates another account's settings and lists profiles.
- The preflight and verify scripts run inside a read-only transaction.
- After containment:
  - anon and authenticated are refused SELECT and DELETE on all six tables, plus INSERT, UPDATE and `setval` where tested;
  - every `service_role` operation the apps use still works;
  - no row changed.
- The generated rollback restores privileges and RLS flags exactly and changes no row.
- Containment re-applies cleanly (idempotent).
- **Not covered locally:** Supabase's own managed objects, the real PostgREST and GraphQL front ends, and the live database's actual views and functions. Preflight C3, V5 and V6 cover those.

## Did anyone use the exposure? (Logs Explorer, read-only)

Run in Dashboard → Logs → Logs Explorer. Retention depends on the plan, and the field names can differ between log versions.

```sql
select request.path, payload.role, count(*) as requests,
       min(timestamp) as first_seen, max(timestamp) as last_seen
from edge_logs
  cross join unnest(metadata) as m
  cross join unnest(m.request) as request
  cross join unnest(request.sb) as sb
  cross join unnest(sb.jwt) as jwt
  cross join unnest(jwt.authorization) as auth
  cross join unnest(auth.payload) as payload
where request.path like '/rest/v1/suite_%' or request.path like '/graphql/v1%'
group by request.path, payload.role
order by requests desc
```

- Any `anon` or `authenticated` request to `/rest/v1/suite_saved_items`, `suite_users` or `suite_user_settings` means someone other than the suite apps' servers read or changed that data.

## After containment (each a separate decision)

1. **Sessions.** If the logs show anon reads of `suite_saved_items`, or can't cover the exposure period, revoke all users' sessions so every stored refresh token stops working (everyone signs in again). This isn't reversible, so it's the owner's call.
2. **Stop storing raw tokens.** Store them encrypted with a server-side key, or keep only an opaque reference. This is a code change in every suite app.
3. **Default privileges.** Supabase grants anon and authenticated on every new table in `public`. Every future suite migration must enable RLS and revoke those grants in the same file, or the same exposure returns.
4. **C4.** Any other `public` table with RLS off and anon grants (for example a `baseball_*` table) gets the same treatment.

## Independence from the primary-key migration

**Containment can proceed on its own, safely.**
- It changes no key, no data and no `service_role` grant.
- It doesn't touch the `suite_app_current_state` plan (`SUITE_APP_CURRENT_STATE_ISOLATION_PLAN.md`), and that plan's phases are unaffected by it.

**The one condition before Step 1:** preflight C7 (and the logs for any app without recent writes) shows that every live suite app writes through a bypassing key.
