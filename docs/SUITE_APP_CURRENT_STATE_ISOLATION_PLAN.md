# Database-level account isolation for `suite_app_current_state`

Status: findings and a plan only. No SQL has been run and no row has been read or changed by this work. The combined Baseball deployment stays on hold until the checks below pass.

## Confirmed on the Daniel AI Suite database (read-only checks by the owner, 2026-10-30)

| Check | Result |
|---|---|
| Primary key | `app` only, and unique |
| RLS | Enabled, not forced |
| Policies (`pg_policies`) | None |

**Preflight Block 1 (P1–P3, P11), owner's run on 2026-10-30, read-only:**

| Check | Result |
|---|---|
| Total rows | 14 |
| Rows with no owner (`null_owner_rows`) | **0**: no blocker for a `NOT NULL` / primary-key `user_id` |
| Rows whose owner has no profile (`orphan_owner_rows`) | **0** |
| Distinct owners (`distinct_owners`) | **2**: two accounts own saved-state rows |
| RLS enabled / forced / policies | true / false / 0 |
| Tables referencing this one (`referenced_by`) | `(none)`: the key swap needs no extra care |
| Roles that bypass RLS | `service_role` only; `anon`, `authenticated`, `authenticator` false |
| `server_version`, `primary_key`, `other_constraints`, `indexes` | **Not yet reported.** Needed before any migration is proposed. |

**Preflight Block 2 (P4–P7, P14), owner's run on 2026-10-30, read-only, all 14 rows:**

| Result | Detail |
|---|---|
| `ok` or `PRESET_HELD_BY_OWNER` | 11 rows, including the Baseball row of the second account (`baseball__<acct_c3562d>`), which is owned by that account |
| **`P6 KEY_OWNER_MISMATCH`** | **3 rows**: `applied_intelligence__<acct_c3562d>`, `music__<acct_c3562d>`, `nba__<acct_c3562d>`. Each key belongs to the second account's workspace, and each row is owned by `daniel`. |
| `P14 DRAFT_STAMP_MISMATCH` | None reported. A row already flagged P6 is not tested for P14 (first problem wins), so the draft stamp on those three rows was reported separately. |
| `P4 NULL_OWNER`, `ORPHAN_OWNER` | None |

**What the three P6 rows are, and are not.**
- They are not Baseball rows. The Baseball row is correctly owned.
- They match the identity-level problem in answer 3: the other suite apps still map a sign-in onto a preset profile by email, so a second account's key can carry the owner's `user_id`.
- Whether that is another person or the owner signing in under a second account is not visible here. P8 (the identity mapping) and P13 (who wrote under each key, and when) decide it.
- No row has been reassigned. Phase 5 stays report-only.

## Answers

### 1. Which role and credentials the app uses

- **Every table read and write** goes through `suite_storage_supabase._request`. It sends the `[suite_activity] supabase_key` secret, or the `SUITE_SUPABASE_KEY` environment variable, as both `apikey` and `Authorization: Bearer` (`suite_storage_config.get_cloud_config`). The secrets template names that key `YOUR_SERVICE_ROLE_KEY`, and the loader also accepts it as `service_role_key`.
- **The anon key** (`supabase_anon_key`) is used only for Supabase Auth sign-in (`suite_auth._create_fresh_supabase_client`). It never queries a table.
- **Billing** uses its own service-role key (`baseball_billing_supabase`).
- **No request carries the signed-in user's JWT.** The database cannot tell accounts apart. The `user_id` column is the app's own `suite_users.id`, not `auth.uid()`.
- **Evidence the key bypasses RLS, without reading it:** with RLS on and no policies, an anon or authenticated key reads zero rows and every write is refused. Saves and restores work, so the configured key bypasses RLS: the service-role key or a new-style secret key.
- **Not checked here.** Neither worktree has a local secrets file or environment variable, so the deployed key wasn't inspected. To confirm without exposing it, check in the Supabase dashboard which API key the Streamlit secret is (service_role / secret versus anon / publishable).

### 2. Does that role bypass RLS?

- **Yes.** `service_role` has `BYPASSRLS` (preflight P11 shows it).
- "Not forced" only matters for the table owner, which bypasses RLS anyway.
- **So today's RLS stops only the anon and authenticated keys.** For the app's own traffic, the only thing separating accounts is the `user_id` filter in application code.

### 3. Can two accounts write the same `app` key?

Yes, in these cases:

| Case | Key | Status |
|---|---|---|
| **The owner on a demo preset.** The owner's admin profile may switch to `ariel`, `guest` and `test_user` (`_DEFAULT_ALLOWED_WORKSPACES`). A real account bound to one of those profiles writes the same key with a different `user_id`. | `<app>__ariel` | Live |
| **The account-isolation bug.** A signed-in account resolved to workspace `daniel` and wrote the owner's unscoped keys. Fixed on this branch only. The deployed Baseball code and every other suite app checked still have the dict-only session checks. | `baseball`, `investment`, … | Live outside this branch |
| **The shared fallback workspace.** An account whose profile can't be resolved gets `user_unidentified`, the same id for every such account. | `baseball__user_unidentified` | Edge case |
| **The health probe.** One key for every account, by design. | `baseball__health_probe` | Harmless content, but the takeover happens every time |
| **The Command Center.** It reads and writes every app's key for the active workspace, so each case above applies to every app. | all | Live |

- **Ordinary accounts don't collide.** On this branch a new email claims its readable profile id only when `suite_users.external_id` (UNIQUE) has no holder, and re-checks after the claim. Otherwise it gets `<id>_<hash of the auth user id>` (`suite_auth.resolve_account_profile_id`).

**A separate, identity-level problem that the primary key does not fix:**
- **The rule.** Before 2026-10-27, any email containing `daniel` or `ariel` became that profile (`_legacy_external_id_from_email`).
- **Still live elsewhere.** The Command Center, Investment, Music, NBA, Future Lens and Applied Intelligence checkouts here still use that rule as their primary rule (`_infer_external_id_from_email`).
- **Effect.** Such an account gets the owner's (or Ariel's) `suite_users.id` and is the same account as far as the database knows: it reads and writes those rows legitimately.
- **Scope.** This matters wherever sign-in is enabled for people other than the owner.

### 4. Can an upsert replace another account's row?

**Yes.**
- **How.**
  - `save_current_state` without `expected_updated_at` sends `POST` with `Prefer: resolution=merge-duplicates` and no `on_conflict`.
  - PostgREST then runs `INSERT … ON CONFLICT (app) DO UPDATE` on every column in the body, `user_id` included.
  - An account posting a key another account holds replaces that row's page, summary, metrics and revision, and **takes over its `user_id`**.
- **Why nothing of the old row survives.** The metrics merge read before the write is filtered by the writer's own `user_id`, so it never sees the other account's metrics, including the verified recovery snapshot, and keeps none of them.
- **What the original account sees.** Its next read, filtered by its own `user_id`, finds nothing, so it sees an empty or new account. Its next save takes the row back, and the other account's state is lost in turn.
- **Where the plain upsert runs.**
  - Every state save in the deployed Baseball code (`main` checkout `0c00c76` has no compare-and-set).
  - Every other suite app.
  - The health probe on this branch.
- **This branch's Baseball saves.** They always use compare-and-set (`suite_cloud_state._save_guarded_state` → `_save_state_if_revision`).
  - The `PATCH` is filtered by `app`, revision and `user_id`, so it can't match another account's row.
  - The first insert gets a duplicate-key 409 and is reported as not written.
  - So the colliding account can't save that key, but nothing is overwritten. That refusal isn't covered by a test, because the fake cloud keys rows by account.

### 5. Is `(user_id, app)` the right key?

- **Yes, with three conditions.**
  - **No ownerless rows.** A primary key column can't be null, and `user_id` is nullable today. Preflight P4 must return 0. If it doesn't, the owner decides per row: either assign it, or use alternative B, a `NULLS NOT DISTINCT` unique index with no primary key.
  - **Every reader filters by `user_id`.** Today one row per `app` is guaranteed by the key. After the change an unfiltered read could return any account's row.
    - On this branch every read filters, or is refused when sign-in is on and no account resolves.
    - The other apps must be checked before Phase 4.
  - **Every writer sends `user_id`.** A writer that sends none (a sign-in-less install with no `suite_user_id`) would fail after `user_id` becomes `NOT NULL`. Preflight P4's recent ownerless rows would show such a writer.
- **Existing upsert targets.**
  - A plain upsert without `on_conflict` follows the primary key, so after Phase 4 old code in every app upserts on `(user_id, app)` automatically. That is the safe direction.
  - Code that names `on_conflict=user_id,app` works from Phase 2 onward, whichever key is in place.
  - The compare-and-set path filters by `user_id` already and needs no change.
- **What it doesn't fix.** The shared-identity problem (§3) and the shared `user_unidentified` / health-probe keys. Those need the code changes in §6.

### 6. Policies and server-side checks

- **RLS policies.**
  - Keep RLS on with no policies on this table: deny-all for anon and authenticated is right for a service-role-only backend. Don't add a permissive policy.
  - Optionally `REVOKE ALL … FROM anon, authenticated` as a second guard (reversible with `GRANT`).
- **Check every other suite table.** The original migrations **disable** RLS on `suite_users`, `suite_saved_items`, `suite_user_settings`, `suite_activity_events` and `suite_resume_items`. If any is still off and anon has grants (preflight P9 and P10), anyone holding the anon key, which is public by design, can read and write every account's rows through the REST API. This may be a larger exposure than the primary key.
- **Server-side checks (required, because the app's role bypasses RLS):**
  1. **Ownership chokepoint for cloud keys**, the cloud twin of this branch's disk chokepoint. Every key from `_scoped_storage_app` must belong to a workspace the session may use, including keys passed in already scoped (`x__ws`). Unscoped keys are allowed only for the owner's profile. Anything else is refused and recorded.
  2. **Refuse the shared fallbacks.** Never read or write as `user_unidentified`, and never create a `suite_users` row for it.
  3. **Health probe.** Use a per-account key, or skip the write when sign-in is on.
  4. **The plain upsert names `on_conflict=user_id,app`**, after Phase 2.
  5. **Before sign-in is enabled for other people in any suite app,** port that app's profile-id rule (no substring matching), the session-proxy fix and the `user_id`-filtered reads.
- **Later, not now:** per-user JWTs with RLS policies on `auth.uid()`. That needs an `auth_user_id` column on `suite_users` and changes to every app.

### 7. Could records have been misattributed?

**Yes. Four ways are possible, and none is proven or ruled out without the preflight:**

| Way | What it would look like |
|---|---|
| **Takeover of the owner's unscoped rows during the bug window.** A non-owner account resolved to `daniel` and saved with the deployed plain upsert. | The owner's unscoped row (`baseball`, and possibly other apps') now has another account's `user_id` (P6). Or it still has the owner's id but content written by the other account, if the owner's next save took it back with the owner's own local state (P7 dates). |
| **Shared identity before 2026-10-27, and still in the other apps.** | Sign-ins whose email contains `daniel`/`ariel` (P8), writing under the owner's or Ariel's `suite_users.id`. The table can't separate them; the activity dates and the content can. |
| **Demo preset keys.** | `<app>__ariel` / `__guest` / `__test_user` owned by the owner where the real profile also signs in, or the reverse (P6 with the preset exception removed). |
| **Own data under the owner's key** (noted in the Stage B doc). | Visible only in P6. With the primary key on `app`, this is the takeover case, not a separate row. |

- **Correction to the Stage B doc.**
  - It said leaked data went into "the receiving account's own row" and that "no account's row was written by another account".
  - That holds only for this branch's compare-and-set saves and for a database keyed by account.
  - With the confirmed key on `app` and the deployed plain upsert, a write under the owner's key would have replaced the owner's row.
  - The doc is corrected.

## Migration plan

Each phase needs the owner's approval. Phases 0, 1, 2 and 3 change no existing row. The SQL is in `docs/sql/`: the preflight is read-only, and the draft is not under `supabase/migrations` so no tool applies it.

| Phase | What | Changes data? | Rollback |
|---|---|---|---|
| **0. Preflight** | Run `suite_app_current_state_preflight.sql` on the Daniel AI Suite project, one block at a time (see "Reading the preflight" below). Review every flag before going on. | No (SELECT only) | Not needed |
| **Backup** | Export the table, and the suite tables P9 flags, from the dashboard (CSV, read-only). Confirm the project's backups or PITR window covers today. | No | Not needed |
| **1. No takeover** | A `BEFORE UPDATE` trigger refuses any update that changes `user_id`. A colliding plain upsert fails visibly instead of replacing the row. Works on today's key, for every app at once. | No | Drop the trigger and the function |
| **2. Per-account index** | `UNIQUE (user_id, app)`, built concurrently. It can't fail while `app` is unique. | No | Drop the index |
| **3. Code** | The §6 server-side checks in Baseball. In every app: reads filtered by `user_id`, and `on_conflict=user_id,app` on the plain upsert. Deploy to Dev first. | No | Revert the code. Compatible with phases 1 and 2 |
| **4. Primary key** | Alternative A: `user_id NOT NULL`, primary key `(user_id, app)` using the Phase 2 index, in one locked transaction that aborts on any ownerless row. Alternative B only if ownerless rows must stay. | Schema only | Clean while no app key is held by two accounts (check query in the draft). After that, roll back code only and keep the schema: going back would mean deleting or renaming an account's row, which this plan never does |
| **5. Misattributed rows** | Nothing automatic. Each row P6/P7/P8 flags is reported to the owner with its dates. Any repair is a separate, approved step, preceded by a copy of that row. | Only if approved | Restore the copied row |

**Preservation.** No phase deletes, moves or rewrites any of these:
- saved drafts (`draft_archive_teams` in `metrics.full_session`);
- verified recovery snapshots (`metrics` → verified board snapshot);
- queues;
- leagues;
- preferences (`suite_user_settings`, untouched);
- any account state.

Phase 4 only changes which columns form the key. Every row keeps its `app`, `user_id` and content.

### Reading the preflight

Six blocks, each one statement; the SQL editor shows only the last result set, so run them one at a time. Output is safe to share: no metrics, payloads, tokens, user ids or full emails. Profiles other than the presets appear as `acct_<6 hex>` (a pseudonym; the file has a private query to map them back). Tested locally with `scripts/sql_tests/suite_app_current_state_preflight_test.sh`: 36 checks, every block read-only, every flag raised by its case, nothing sensitive in the output.

| Block | Shows | What decides the next step |
|---|---|---|
| **P1–P3, P11** | Version, primary key, indexes and constraints, tables referencing this one, RLS and policies, row / ownerless / orphan / owner counts, which roles bypass RLS | `null_owner_rows` and `orphan_owner_rows` must be 0 for alternative A. `referenced_by` must be `(none)`. |
| **P4–P7, P14** | One line per row: key, the account the key belongs to, the row's owner, the owner stamp inside a saved live draft, size, and a `flag` | Every flag other than `ok` / `PRESET_HELD_BY_OWNER` is examined with the owner before any phase. `P6 KEY_OWNER_MISMATCH` on an unscoped key is a takeover of the owner's row. `P14 DRAFT_STAMP_MISMATCH` means the owner's row holds a draft another profile created. |
| **P13** | For each state key, every account that wrote activity events or resume items under it, with first and last dates | `writer_is_row_owner = false` means another account wrote under that key. Their state saves would have gone into the same row. The dates bound when. |
| **P8** | Sign-ins whose email contains "daniel" or "ariel" (masked), the profile the legacy rule gave them, and whether a profile records that email; every profile | A sign-in mapped to `daniel` with `(no profile records this email)` is a different person who shared the owner's account under the legacy rule. |
| **P9–P10** | RLS, policies and anon / authenticated / service_role access on every suite and baseball table, exposed tables first | Any table with RLS off and anon or authenticated access is exposed like the three contained ones. |
| **P12** | Per-row hashes and the table fingerprint (same formula as containment C6) | Saved before any phase and compared after it. |

**What the preflight can't tell.** A takeover that the owner's next save reversed leaves the owner's `user_id` on the row; only P13's dates and the row's own content would show it. The live-draft stamp exists only when a live draft was saved. The device id in a saved session isn't used: on Streamlit Cloud it identifies the server, not the person.

### Tests

**Before Phase 3 ships, on the branch (fake cloud):**
- Teach `FileStore` the real key: one row per `app`, with upsert semantics that replace `user_id`. Then:
  - **Owner and another account writing the same key:** today's plain upsert takes the row (a failing test that documents the bug); compare-and-set refuses; with the Phase 1 trigger simulated, the plain upsert errors.
  - **The same after the key change:** both accounts keep their own row.
  - **Ownership chokepoint:** a session can't read or write a key outside its workspaces, including an already-scoped `x__ws` key; `user_unidentified` is refused.
  - **Readers:** every current-state read sends a `user_id` filter when sign-in is on.
- Rerun the full Stage B regression against the `f8ffbbe` baseline, as before.

**On Dev, in order, with two isolated test accounts (never the owner's):**
1. Preflight on the Dev project.
2. Phases 1 and 2 on Dev.
3. Test account A writes a key. Test account B's plain-upsert path writing the same key fails, and A's row is unchanged (`user_id`, revision, metrics hash).
4. Phase 3 code on Dev, then Phase 4 on Dev.
5. Both test accounts save, restore on a second device and sign out and in. Each sees only its own work.
6. The owner's admin switches to a preset workspace while that profile's test account is signed in elsewhere: two rows, no conflict.
7. Production gets the same phases only after Dev passes and the owner approves.

### Verification after each phase

| After | Check |
|---|---|
| Phase 1 | The trigger is listed on the table. A Dev-only, test-account-only update that changes `user_id` fails with 42501. |
| Phase 2 | The index exists and is valid (`pg_index.indisvalid`). |
| Phase 4 | P1–P3 shows `PRIMARY KEY (user_id, app)` and zero ownerless rows. P12's row count and per-row `metrics` hashes are identical to the pre-migration export. |
| Every phase | The owner's own rows still restore on the Dell and the phone: board, Saved Draft Library, queue and leagues (read-only spot check in the app). |
