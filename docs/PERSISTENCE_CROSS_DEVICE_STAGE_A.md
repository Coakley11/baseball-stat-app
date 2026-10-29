# Page settings and cross-device sync — Stage A

Branch `fix/cloud-restore-hydration`, on top of the Simulator restore work (`23c707e`, `8ae73a5`).
Local only: not pushed, not deployed, and not checked against the real Supabase project.

## Why the Historical Explorer filters reset

This was not one bug. Four mechanisms combined:

1. **A workspace apply on a rerun overwrote the edit that triggered the rerun.**
   - The account workspace (`full_session`) is applied on a rerun after:
     - the first cloud sync finishes late,
     - sign-in completes,
     - a forced sync, or
     - after navigation such as Historical → Trend Value → Historical.
   - That apply writes every page's widget keys and replaces `page_filter_state`.
   - Streamlit puts the browser's new widget value into `_new_widget_state` *before* the script runs. A session-API write in the same run wins over it.
   - So the change the user had just made (e.g. HR min 40) was replaced with the saved value.
   - The page's own dirty flag is set later in the run, so the apply could not tell an edit was in flight.
2. **First-render defaults were saved as a user edit.**
   - Every `flush_*` in the page-state modules passed `local_edit=True` (historical, career totals, valuation, projections, leaderboards, fantasy).
   - The first render happens while sign-in or the cloud restore is still under way, so its defaults were marked as a local edit.
   - The edit guard then refused the account's saved filters when they arrived. Result: defaults after a late sign-in.
3. **A stale device could not catch up.**
   - Example: a Dell session opened before the phone saved.
   - Its saves were refused (compare-and-set), but nothing merged the newer data in.
   - Ordinary navigation never re-read the cloud, so the device stayed stale until a refresh.
   - On refresh, its unsaved local edits were lost.
4. **The staleness check compared whole seconds.**
   - Two writes within the same second looked equal.
   - A stale write could therefore pass.

Other pages with widget-backed settings had the same exposure through mechanisms 1–3:
- Career Totals
- Valuation
- Projections
- Leaderboards
- Fantasy
- Trend Value

## What changed

| Piece | Change |
|---|---|
| `workspace_merge.py` (new) | Three-way merge of the account workspace against a per-session *base*, which is the last blob loaded or written. The rules are below. |
| `suite_user_persistence.sync_workspace_protocol` | Detects widget edits made this run (`widget_edits_this_run`) before applying the workspace, merges local against the cloud instead of replacing it, and re-applies the in-flight edits afterwards. If anything local survived, it marks the session dirty so it saves. Handles "reapply" (a requested re-read of the account). |
| `suite_cloud_state.save_cloud_full_session` | When the cloud has moved (a plan refusal or a CAS failure), rebases the outgoing state onto the fresh cloud copy and retries once. It records the new base, and asks for a reapply when the merge took remote data, so the page shows it. Board-mutation saves (Save Draft Board Now, picks) are **not** rebased. They keep the board's own reconcile prompt (`draft_board_reconcile`). A board changed on **both** sides is never merged by the generic path, whatever the save reason. The rebase is refused, and a sync leaves the session as it is, so the board prompt asks. |
| `cloud_write_blocked_by_newer_data` | Compares timestamps as floats, not whole seconds. |
| `baseball_persistent_state` | When the sidebar page changes, a metadata-only check sees whether the account moved. If it did, the next sync merges it in. Registers a finalizer that rebuilds the derived `baseball_workspace_state` from the merged pages. |
| `flush_*` in the six page-state modules | `local_edit=pending`: only a widget callback counts as an edit. |
| `streamlit_app.py` | Renders the conflict banner (`render_workspace_conflicts`) under the persistence messages. |

### Merge rules

- **Player lists are merged as sets.** This covers the draft queue, watchlists, focus players and dismissals.
  - Additions and removals from both sides are kept.
  - Example: Dell has `[B, C, D]` and the phone added `E`. The merge is `[B, C, D, E]`.
  - The list size never decides the result.
- **Boards and draft states are atomic.** These are the Simulator table/state, live draft state, snapshots, league context and the draft archive.
  - One side changed: that side wins whole.
  - Both changed: a conflict.
  - They are never spliced pick by pick, so an undo stays an undo.
  - Bookkeeping inside a block is ignored when comparing: keys with a leading `_` (such as `_persisted_at` or pool diagnostics), plus `last_updated_at`, `updated_at`, `last_write_reason` and `updated_by_page`. Merely opening the Simulator on two devices is not an edit.
  - A Simulator board changed on both sides is handed to `draft_board_reconcile`. It is not handled by the generic conflict banner.
- **Settings merge per field.**
  - One side changed a field: that change is taken.
  - Both changed it to different values: a conflict.
- **Internal keys** (leading `_`) stay local.
- **Conflict handling:**
  - The account keeps the other device's value, and this device keeps showing its own.
  - The banner names the field and offers **Keep this device's version** (save local) or **Use the saved version** (re-read the account).
  - Neither side is discarded without a choice.

## Tests

- `tests/test_workspace_merge.py`: unit tests for the merge rules, including the 3-vs-4 queue case, the same-second stale write and undo surviving.
- `tests/test_page_settings_sync.py`: AppTest end-to-end, with real navigation and widget lifecycle, two devices and a compare-and-set fake cloud.
  - **Navigation and refresh:** Historical filters survive navigation, refresh and a late sign-in.
  - **Phone ↔ Dell:** filters made on one device show on the other.
  - **Stale device:** a stale Dell merges the phone's queue and filters.
  - **Conflict:** keep-local works.
  - **Board isolation:** research edits never touch the board.
  - **Simulator picks:** a pick on the phone reaches an open Dell session, later saves keep working, and on an account with a saved board an unsaved pick is autosaved and survives navigation.
  - **Failure and isolation:** a failed save keeps local work and saves once the read backoff (max 60 s) has passed; another account stays isolated.
- `tests/test_cloud_restore_lifecycle.py` (from `8ae73a5`) still passes.

## Not covered by Stage A (staged plan)

**Stage B: account-level data outside `full_session`**
- **Account preferences doc** (`baseball__ws_account_prefs`: active league or draft, source overrides, research mode).
  - It is last-writer-wins: `expected_revision` is never passed, and the whole doc is rebuilt on write.
  - Needs CAS plus a per-field merge.
- **Saved Draft Library manifest.** Published last-writer-wins and needs the same treatment.
  - The archive itself (`draft_archive_teams`) is in `full_session` and is atomic for now.
  - Per-entry merge would let two devices each save a draft.
- **AMI and Command Center.** Questions and insights (`suite_saved_items`) and Continue (`suite_resume_items`) depend on `suite_storage.py`.
  - This checkout does not contain `suite_storage.py`. It comes from the Command Center repo on `sys.path`.
  - Without it, cross-device lookups quietly return nothing.
  - This needs a deploy-time check, or a vendored copy.
- **Solo Live Draft and HOF Case Mode.** They are in `full_session` (atomic), so they ride on Stage A.
  - They have no dedicated end-to-end test yet.

**Save volume (reported by the feature-completion session)**
- Leaving Live Draft Room saves twice: `live_draft_setup_page_leave`, then `user_page_prefs:live_draft_setup`.
  - Neither reason is fingerprint-deduped.
  - Fold them into one save, or add both reasons to `_RENDER_SNAPSHOT_SAVE_REASONS`.
- Historical Explorer calls `force_save` 2–3 times per visit. Unchanged calls already skip the write (2accb55).

**Stage C: cosmetic state**
- Expanders, tab choice, column widths. These stay per device.

## Pre-existing issues found while testing (same on `8ae73a5`, not changed here)

- **A leftover local workspace can leak into a fresh device's restore.**
  - Example: `data/workspaces/daniel/` with `data/suite_active_workspace.json` pointing at it.
  - In a test tree, a Live Draft room owned by `daniel` entered another account's saved blob.
  - Its draft settings then reset the shared min-games (Trend Value `trend_min_g`) to the default on the next save.
  - This is the case `test_live_draft_workspace_isolation` already covers (currently failing).
  - On a server whose disk is shared between users it is an isolation bug, and should be fixed before Dev.
- **A brand-new account's first board is not autosaved.**
  - With no saved workspace at all, the empty-account autosave block holds the first picks until **Save Draft Board Now** (in the test, navigating away did not save them).
  - Once the account has a saved workspace, picks autosave as normal.

## Verification gap

All tests use a fake cloud that enforces compare-and-set. Before Dev, run one manual pass against a **test** account on the Dev Supabase project, with a real laptop and a real phone:
- save the board,
- refresh,
- pick on the phone,
- navigate on the laptop,
- edit filters on both.
