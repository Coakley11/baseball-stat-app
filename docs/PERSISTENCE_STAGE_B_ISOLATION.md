# Account isolation and account-wide sync — Stage B

Branch `fix/cloud-restore-hydration`, on top of Stage A (`f8ffbbe`, see `PERSISTENCE_CROSS_DEVICE_STAGE_A.md`).
Local only: not pushed, not merged, not deployed, and not checked against a real Supabase project.

## 1. Cross-account leak through server-local files (fixed)

On Streamlit Cloud every session of the app shares one server `data/` directory. That directory holds:
- each workspace's `data/workspaces/<ws>/baseball_user_state.json`;
- the legacy global pointer `data/suite_active_workspace.json`, which names `daniel` by default.

### How another account's data got in

1. **The ownership code only recognised plain dicts.**
   - It checked `isinstance(session_state, dict)` in five places in `suite_workspace_registry` and in `suite_workspace.load_persisted_workspace_id`.
   - In the running app, `st.session_state` is a `SessionStateProxy`, which is not a dict.
   - So for every signed-in user, the code treated the session as having no account:
     - `get_owned_workspace_id` returned `""`;
     - `list_owned_workspace_ids` returned the demo presets, including `daniel`;
     - the active workspace was read from, and written to, the shared global pointer.
2. **The empty owner became `daniel`.**
   - `hard_clamp_owned_workspace_before_scoped_load` called `normalize_workspace_id("")`, which returns `"daniel"`.
   - Every single-seat account was therefore clamped onto the owner's workspace (`"stage": "single_seat_hard_clamp", "owned": "daniel"`), on the unscoped cloud key `baseball`.
   - It was clamped back later in the run, but code that read `_suite_active_workspace_id` in between saw `daniel`.
3. **Reads inside that window used the owner's files.** Two paths did this:
   - **Live Draft save enrichment.** `enrich_save_payload_with_live_draft` recovered "this account's" room from `_load_raw("baseball", workspace_id=session["_suite_active_workspace_id"])`, which read `data/workspaces/daniel`. The owner's room was then uploaded into the other account's own cloud row.
   - **Draft recovery scan.** The migration scan (`discover_workflow_migration_sources` / `_disk_migration_candidate_workspace_ids`) always added `daniel` and `daniel_cohen11` for every signed-in account. The authenticated-migration writeback could then pull the owner's drafts in.
   - At startup, the owner's **Saved Draft Library** reached another account's session (`test_account_isolation_app` on the old code: "Owner's league").
4. **Writes in that window could hit the owner's local copy.**
   - A save could target the owner's workspace file.
   - Restore prefers disk when a disk copy exists, so the owner's next session on that server would load it.

### What is and isn't affected

| Question | Answer |
|---|---|
| Server-local files treated as account data | Yes. Fixed. |
| One user's active-workspace pointer affecting another user's session | Yes, the global pointer. Fixed. |
| One account's draft, league or settings loaded into another account | Yes. Fixed. Observed: the Live Draft room and the Saved Draft Library. The queue and watchlist ride in the same file. |
| Uploaded to Supabase | Yes, but into the receiving account's **own** row. Every query is filtered by that account's `user_id`, so no account's row was written by another account. |
| Production-style startup or only the test fixture | Production style. The real `streamlit_app.py`, with the real session proxy, reproduces it (see `trace_leak` below). It needs the owner's files on the same server disk. |
| AMI data | **The history tables were not exposed.** Question history, Continue cards and saved insights are in Supabase tables keyed by `user_id`. **The workspace-file copies were.** The pending insight, return context and dismissed ids are stored in the workspace file, so they rode the same path as the Library. |

### What changed

Each cause is fixed where it happens, and one chokepoint now enforces ownership.

| Piece | Change |
|---|---|
| `suite_workspace_registry` | Accepts any mapping session, including `SessionStateProxy`. A signed-in account never resolves to, and never writes, the global pointer. |
| `suite_workspace` | `load_persisted_workspace_id` is account-aware for the proxy. `persist_active_workspace_id` never writes the shared pointer for a signed-in account. An empty session key no longer becomes `daniel`. An unresolved owner no longer clamps to `daniel`. |
| `suite_auth` | Both clamps use `_normalized_or_empty`: an unresolved id stays `""` and never becomes `daniel`. |
| `suite_user_persistence` (chokepoint) | `_load_raw`, `save_user_state` and `reset_user_state` refuse a workspace that the running script's signed-in account is not allowed to use (`workspace_disk_access_allowed`). A refusal is recorded in `_suite_workspace_access_refused`. The legacy single-user `data/app_state.json` only ever seeds the default owner's workspace. |
| `live_draft_state` | Room recovery reads this account's resolved workspace, never a raw session key. |
| `workflow_persist_guard` | The draft recovery scan covers only workspaces the signed-in account owns. The owner keeps their own legacy sources. |
| `suite_cloud_state` | Five `isinstance(ss, dict)` checks now accept the proxy. One of them refuses a board save whose cloud write fell back to a workflow-only payload and dropped the picks. Before this change it never ran. |

### Tests

- **`tests/test_account_workspace_isolation.py`** (13 tests). Each uses a non-dict mapping session and a private data directory seeded with the owner's files. On `f8ffbbe`, 11 fail; the 2 controls pass. They cover:
  - resolution, the startup clamp, the shared pointer and a URL naming another workspace;
  - the disk read, overwrite and reset chokepoint, while the owner still reaches their own files;
  - the legacy file, the recovery scan and Live Draft enrichment.
- **`tests/test_account_isolation_app.py`** (2 AppTest tests). The real app resolves its own workspace, with no harness patch, against the owner's leftover files. Both fail on `f8ffbbe` and pass now. The checks:
  - a second account, on a Dell and on a fresh phone, never sees the owner's room, Library, queue or settings;
  - its cloud row has none of them;
  - the owner's files and the pointer are byte-identical afterwards;
  - two accounts on one server keep their own work on disk and in the cloud.
- **Repaired test fakes.** `test_live_draft_workspace_isolation` and `test_foreign_blob_restore` were failing on the base. Their fakes had no `query_params`, or no complete sign-in, so they never reached the isolation check. With the fakes repaired they now run and pass.
- **Harness.** `cloud_restore_harness.start_cloud(real_workspace=True)` is available for other isolation tests.

## 1b. Signing out, then in as another account on the same browser (fixed)

- **What happened.** Logging out removed the identity but left the account's whole workspace in the browser session: page filters and widget values, queue, Library, leagues, the merge base, the revisions it had seen, and the Ask AMI conversation.
- **Consequence.** The next account to sign in on that tab saw the previous account's filters (`test_signing_out_and_in_as_another_account_in_one_browser_inherits_nothing`: B's Historical Explorer showed A's HR filter). Its next save could put that data into its own account.
- **The fix.**
  - `suite_user_persistence.clear_account_session_state` runs on log out and when a different account signs in (`_persist_auth_session`, scope change).
  - It clears every key the workspace persistence carries (registered by `baseball_persistent_state.clear_baseball_account_workspace`), the widget values those pages saved, the per-account bookkeeping and `_ami_assistant_*`.
  - The current page is kept.
  - A signed-out guest's own edits still carry into the account it signs in to, as Stage A requires.
- **Copies outside the saved keys** (found by running the real app after the first fix):
  - The queue was rebuilt from its survival copy (`_live_draft_queue_last_good`), so the signed-out tab still showed it.
  - Other copies: `draft_state`'s write records (`_draft_new_*`), the session's cached copy of the cloud workspace (`_suite_full_session_blob_*`), the Library pre-write backups (`_suite_draft_archive_*`) and Ask AMI's page context (`_ami_context_by_page`).
  - All of these are now cleared too.
- **Unsaved-edit markers** (`*_dirty`, `*_pending_sync`, `*_last_local_edit_ts`) are cleared as well.
  - Clearing the queue but leaving `_draft_queue_persist_dirty` made the restore after sign-in keep the empty session queue as a local edit ("local_dirty_or_pending").
  - The next save then wrote `draft_state.queue = []` into the account. The real app showed this for the same account signing back in. Another account signing in on that tab could have its queue wiped the same way.
  - Clearing the markers was not enough. The sidebar normalizes the queue on every run (`_workflow_normalize_draft_queue` → `draft_state.sync_draft_queue`), and that always marked a local edit, even empty → empty. So the signed-out runs set the marker again.
    - This is harmless on a fresh device, where the first restore runs before the sidebar.
    - It is not harmless on the same tab after logout.
  - `sync_draft_queue` now marks an edit only when the queue changes. Add, Remove, reorder, and dropping a drafted player still mark one (`test_draft_state.QueueNormalizeIsNotAnEditTests`).
  - The AppTest now checks the account's `draft_state.queue` is never saved empty.
  - The unit test checks that no session value holds the previous account's queue, Library or Ask AMI text, and that no edit marker is left.
- **The same account signing back in** gets its work from the cloud, not from a copy left in the tab. A copy kept in the session could put older work over newer edits made on another device in the meantime. `test_signing_out_and_back_in_as_the_same_account_brings_its_work_back_from_the_cloud` (AppTest) shows the filter and queue coming back.
- **Tests.**
  - `test_account_workspace_isolation.AccountChangeInOneBrowserTests` (unit).
  - The two AppTests above, which press the real **Log out** button. The account-switch AppTest fails on `5a09c4b` and passes on `3b139b6`.
- **An older test changed on purpose.** `test_baseball_auth_workspace_regression.test_completed_handoff_logout_then_login_survives_ordinary_reruns` asserted that `draft_archive_teams` stays in the session through logout. It only passed when `baseball_persistent_state` had not been imported yet; the app always imports it. It now imports that module, as the app does, and asserts the Library leaves the session. Its auth-handoff and rerun-guard checks are unchanged.

## 2. Queue, watchlists and tracked players: ordered, removal-aware

Stage A merged these as sets. That honoured a removal relative to the base, but lost order: the result was always remote order plus local additions. The new rule is `workspace_merge._ordered_merge`, a three-way merge against the base:

- **Membership.**
  - An item the base had, and either device dropped, stays removed. That covers a deliberate removal and a pick that consumed the player.
  - An older copy never brings a player back.
  - Additions from both devices are kept.
  - There are never duplicates.
- **Order.**
  - The device that did not reorder follows the one that did.
  - The other device's additions go just before the item that followed them. An append (Add to Queue) stays at the end.
- **Both devices reorder the same items differently.** That is a conflict:
  - this device shows its order, and the account keeps the other device's;
  - the banner asks **Keep this device's version** or **Use the saved version**.
- **Covered lists:** `draft_queue`, `draft_state.queue`, the watchlists (`watchlist_focus` / `watchlist_favorites`), `draft_assistant_focus_players` and `workflow_favorite_targets`.
- **View history** (`workflow_recently_viewed`, recent compare pairs) keeps this device's copy. Stage A raised a false conflict when both devices viewed players.
- **Queue model compatibility.** The model on `feature/baseball-completion@7122f0b` is still a name list, which is compatible. For its new keys:
  - `_draft_queue_consumed` merges per source, as a dict;
  - `_simulator_board_epoch` takes the maximum.

Tests:
- `tests/test_workspace_merge.py`: 10 queue cases.
- `tests/test_queue_sync_app.py` (AppTest, two devices, the real `draft_state` functions):
  - a removal plus a move-to-top on the phone is never undone by the stale Dell;
  - a Dell reorder plus a phone addition both survive;
  - a reorder on both devices keeps both orders until the user picks one.
  - On `f8ffbbe` the second and third fail (the reorder was lost).

## 3. Account preferences

- **`suite_storage` was missing.**
  - `suite_account.load_settings` / `save_settings` (and the saved-item reads) imported `suite_storage` with no fallback.
  - That module lives in the Command Center repository, not here, so on a Baseball deploy every account preference read and write raised.
  - Active league / draft, the Simulator and Live overrides and Research Mode never synced through the account document. Only the full-session copy carried them.
  - `suite_account._storage()` now falls back to `suite_storage_supabase`. That is exactly what `suite_storage` calls in cloud mode, with the same tables, keys and `user_id` scoping, so no second store is involved.
- **Stale rewrite.**
  - `write_account_fantasy_preferences` rebuilt the whole document from this session, so a stale device toggling one control reverted the others.
  - It now patches only the fields this session changed since it last applied or wrote the document (`fields_changed_on_this_device`, measured against a per-session base), through `update_account_fantasy_preference_fields`.
- **Concurrent write.** The settings row has no compare-and-set. A concurrent write by the other device is caught on readback, and the patch is re-applied once onto the newer document.
- **Inside the full-session blob:**
  - `fantasy_league_context_state` merges **per league**: each league whole, the active league as its own field, deletions as a set. Editing league A here and switching to league B there are two changes, not a conflict.
  - The two explicit-choice records (`fantasy_source_override_selection`, `fantasy_research_mode_selection`) are never mixed field by field. When both devices chose, the later `selected_at` wins.
- **Tests:**
  - `test_account_fantasy_preferences_cross_device.py`: a stale research toggle keeps the league chosen elsewhere; a stale league choice keeps the override chosen elsewhere; a racing write keeps both changes.
  - `test_workspace_merge.py`: a filter here plus a league switch there keeps both; the same league edited on both is a conflict on that league only; choices; deletions.
  - `test_suite_account_storage_fallback.py`.

Scoring format, projection style and research settings live in the league context and in the global keys (`fantasy_draft_projection_style`, `draft_shared_settings`). They ride on the full-session merge above.

## 4. Saved Draft Library

- **`draft_archive_teams` merges per saved draft**, keyed by `draft_id`.
  - A draft saved on each device keeps both.
  - A deletion stays deleted.
  - The same draft edited on both is a conflict on that draft only (`("draft_archive_teams", "@<id>")`).
  - Stage A treated the whole Library as one value, so picking a side dropped the other device's new draft.
- **The compact Library manifest** is merged per row when published. The newer content clock wins, and the revision never goes backwards, so a stale device publishing can't roll another device's rename back.
- **Tests:** `test_workspace_merge.py` (3) and `test_library_content_clocks_manifest.py` (stale publish).

## 5. AMI and Command Center history (where it lives)

| What | Where | Scope |
|---|---|---|
| Quick Ask AMI answers and conversation | `st.session_state` only (`_ami_assistant_*`) | Never persisted. That is the design; nothing crosses devices. |
| Get full analysis: Continue card | Supabase `suite_resume_items` (`app = applied_intelligence[__ws]`, `item_key = ai:question:<qid>`) | `user_id` |
| Get full analysis: question context | Supabase `suite_saved_items` (`item_type = analytical_question_context`) | `user_id` |
| Get full analysis: event | Supabase `suite_activity_events` | `user_id` |
| Saved insights and dismissals | Supabase `suite_saved_items` | `user_id` |
| In the full-session blob | Pending insight, return context, dismissed ids, HOF handoff keys | Merged as above |

- **The authoritative interface is the Command Center's `suite_storage`.**
  - In cloud mode it delegates to `suite_storage_supabase`, plus a local SQLite mirror.
  - Before this change, the Baseball deploy could write these rows but could not read context, insights or dismissals back through `suite_account`.
  - The guarded fallback restores those reads.
- **Remaining gaps:**
  - `fetch_saved_item` / `fetch_saved_item_any_app` were removed upstream (commit `57009b3`). The direct context lookup is dead code, so lookup now uses the scan, which covers the latest 200 contexts per app.
  - Cross-device AMI conversation history does not exist. Adding it would be a product decision, and no new store was added here.

## 6. Simulator: a brand-new account's first picks now autosave

- **What happened before.**
  - An account whose read answered "no saved session", with no local copy, was put under the autosave block on every run.
  - The block also returned before the disk save. Navigation did not force a save.
  - The first picks lived in the browser session only, and a refresh lost them.
  - No "saved" status was shown, but nothing warned either.
- **What happens now.** In that state, a confirmed-empty answer to an authenticated read, autosave runs.
  - **Safe because** the write is create-only. The save re-reads first. If the other device created the row meanwhile, the write is refused as stale and merged against the recorded empty base, so two first boards go to the board prompt.
  - **Still blocked:** an inconclusive read, such as a failure or auth not ready.
- **Tests:** `test_page_settings_sync` (the first pick reaches the account without Save Draft Board Now, and a fresh phone shows it) and `test_league_setup_integrity`.

## 7. Save volume

Leaving Live Draft Room saved twice with the same content: `live_draft_setup_page_leave`, then `user_page_prefs:live_draft_setup`. The second is now skipped, but only when the first reached the account, so a failed write still retries. Tests: `test_rerun_save_cost.LiveDraftLeaveSaveTests`.

## 8. A device's own saved value no longer conflicts with a newer explicit choice (regression fixed)

- **Found by the final AppTest run.** `test_same_setting_changed_on_both_devices_keeps_both_until_the_user_chooses` passes on `f8ffbbe` and failed on `5a09c4b`.
  - The phone pressed **Keep this device's version** (the account now holds 30).
  - The stale Dell, which had written 40 itself, reported a new conflict and kept showing 40.
- **Cause.**
  - After a rebased write, the session holds its pre-rebase base until the merged state is applied (`workspace_merge.merge_base`). That keeps a value the page still shows from before the merge from reading as an edit.
  - The whole held base was used, though. So the Dell's own written 40 was measured against the pre-rebase 0 and read as a fresh edit.
  - 5a09c4b's merge changes made the Dell's first save a rebased write, which exposed this.
- **Fix.**
  - With the held base, the session now also holds what it itself showed when it made the rebased write (`_suite_workspace_held_local::`).
  - `merge_base(session, app, local)` works per field:
    - a field that still equals that pre-merge display is unchanged here, so the account's value wins;
    - anything else is measured against what the session wrote.
  - Saved drafts follow the same rule per record.
  - Both merge sites pass this session's state: the restore merge and the rebase before a write.
- **The first attempt was wrong.** It treated a field as stale only when it equalled the pre-rebase base. That fixed this test but broke `test_queue_sync_app.test_a_reorder_on_the_dell_and_an_addition_on_the_phone_both_survive`: the stale Dell's own reorder `[J, B, S]` equals neither the base nor what it wrote `[J, B, S, W]`, so the phone's merged-in W read as removed.
  - Comparing with the session's own pre-merge display handles both cases.
  - Both the queue case and the explicit-choice case are now unit tests.
- **Tests.** `test_workspace_merge.HeldBaseAfterRebasedWriteTests` (6). The AppTests are listed under Regression below.

## 9. Hall of Fame Case Mode survives leaving Career Totals (old defect, fixed)

- **Symptom.** Case Mode and its target were lost on any trip away from Career Totals and back. A fresh phone then got the "off" value that the page wrote on return. This also fails on `f8ffbbe`, so it predates Stage A.
- **Cause.**
  - Sidebar navigation deliberately skips the generic page restore (`_skip_page_restore_for`). Each page restores its widgets from its own canonical state.
  - Career Totals' restore covers only the career filters and minimums. The Case Mode checkbox and target are widget keys, so Streamlit dropped them off-page, and nothing brought them back before the checkbox rendered (as off).
- **Fix.** `career_totals_state.prepare_career_totals_page` restores both from the Career Totals block when they are absent, before anything checks Case Mode. An edit on the page or a HOF resume is never overwritten.
- **Limitation.** Case Mode toggled on Historical Explorer is saved only with that page's global keys. Going Historical → another page → Career Totals shows Career Totals' last saved value.
- **Test.** `test_solo_hof_sync_app.test_hof_case_mode_and_target_follow_the_account`.

## Integration with `feature/baseball-completion@7122f0b` (trial merge only)

- **Scratch merge.** `7122f0b` was merged into `3b139b6` in a scratch detached worktree (`505578a`, kept local and not on any branch). The merge is textually clean. A second trial merge onto `fa4d79b` is also clean (89 files). The `sync_draft_queue` change does not conflict with 7122's queue changes.
- **Files changed on both sides:** `baseball_persistent_state.py`, `draft_room_state.py`, `fantasy_context_source.py`, `streamlit_app.py`, `suite_auth.py` and `tests/test_league_setup_integrity.py`. None overlap in the same hunks.
- **Semantic fit.**
  - Their `clear_queue_for_account_change` (on sign-out and on account switch) sits beside `clear_account_session_state`; both run, and the clearing is the same.
  - Their persisted `_draft_queue_consumed` merges per source, and `_simulator_board_epoch` takes the maximum.
  - A pick that consumes a queued player on one device removes him on the other through the base-relative removal rule.

## Regression on the final code (`fa4d79b`)

Every result here was run on `fa4d79b` itself. The baseline is an unchanged `f8ffbbe` checkout in a scratch worktree. Earlier runs on `5a09c4b` and `3b139b6` are not counted as evidence.

- **Unit and integration tests.** These are all test files except the AppTest suites below, which fail spuriously under load when run inside the bulk run.
  - Baseline `f8ffbbe`: 231 failed, 5 errors.
  - `fa4d79b`: 227 failed, 5 errors, 5297 passed.
  - **No failure is new.** Every failing test also fails on the baseline. These existing failures are mostly stale source-text assertions and missing helpers, such as `is_transient_supabase_error`, unrelated to persistence.
  - **Fixed relative to the baseline:**
    - `test_foreign_blob_restore…test_apply_state_does_not_crash_on_foreign_blob_check`;
    - `test_live_draft_solo_timer_expire…test_four_expires_never_stuck_at_zero`;
    - `test_live_draft_workspace_isolation…test_refresh_after_draft_completion_preserves_workspace`;
    - `test_live_draft_workspace_isolation…test_restored_blob_with_daniel_workspace_rejected_for_cio11`.
  - **Flaky.** `test_live_draft_timer_expiration…test_queue_does_not_override_configured_rule` fails on the baseline and here, and passed once on `3b139b6`. It depends on timing.
- **AppTests (the real app, fake cloud).** 35 of 35 passed, in 1 h 45 min:
  - `test_account_isolation_app`: 4;
  - `test_queue_sync_app`: 3;
  - `test_solo_hof_sync_app`: 2;
  - `test_page_settings_sync`: 10;
  - `test_cloud_restore_lifecycle`: 16.

  Two of these were failing before `fa4d79b`:
  - **HOF Case Mode.** It fails on `f8ffbbe` too (section 9).
  - **Same setting changed on both devices.** It passes on `f8ffbbe` and failed on `5a09c4b` (section 8).

  Both pass now.

## Risks and checks before Dev

- **`suite_app_current_state` key (verify on the Dev project).**
  - The Command Center migrations create the table with `app text primary key`.
  - The composite `(user_id, app)` key is commented out as "optional later", and RLS is disabled on the account tables.
  - If Dev or Production still has `app` as the key, the `user_id` filters in the app code are the only separation between accounts. A non-CAS upsert on a key that two accounts can reach would overwrite the row. One such key is the owner's unscoped `baseball`, which the old clamp briefly used for every account.
  - This needs checking on the real project. Nothing here touched Supabase.
- **Own-data split.** During the old clamp window, an account could have written its own data under the unscoped `baseball` key: still that account's own `user_id`, but not its usual `baseball__<ws>` row. A read-only check of a test account's rows on Dev would show whether this happened.
- The fake cloud (`FileStore`) keys rows by account, so it cannot detect the schema risk above.
