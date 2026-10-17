# Hosted autosave reliability — audit, safeguards and remaining work

Status (October 2026):

* **Implemented and tested against a fake store:** steps 1–3 of the proposed fix below.
  See "What is implemented" at the end.
* **Not verified against the real cloud store.** That needs staging Supabase credentials,
  which were not available. No production data was read or written.
* **Not implemented:** stale-tab protection (another device saved after this tab loaded) and
  step 4.

## How it works today

`suite_user_persistence.sync_workspace_protocol` runs once per browser session before
the sidebar. It reads the cloud blob (`suite_cloud_state.load_cloud_full_session`) and
the disk blob (`_load_raw`), picks the newer (`pick_restore_session`) and applies it.
Autosave (`autosave_if_changed`) and user-action saves (`save_workspace_now(reason=...)`)
then write both disk and cloud.

Guards that exist:

* No blob anywhere on a hosted install → `_mark_workspace_sync_skipped` sets the
  per-run autosave block and `_suite_workspace_sync_skipped_no_apply`.
* The per-run block is cleared at the end of every run
  (`clear_workspace_autosave_block`, end of `streamlit_app.py`).
* User-action reasons (`fantasy_edit`, `draft_edit`, `page_change`, … — the bypass list
  in `save_workspace_now` and `_FORCE_SAVE_CLOUD_REASONS`) skip both the block and the
  "sync not applied" cloud check.

## Findings

1. **A failed cloud read looks like "no cloud data".** `load_cloud_full_session`
   wraps everything in `except Exception: return {}, None`. Not found, network error,
   timeout and permission denied all come back as `({}, None)`.
2. **Failed read + disk copy → stale disk wins and is written back.** If the cloud read
   fails and this container has a disk blob (older), the disk blob is picked, applied,
   fingerprinted, and the next change autosaves it to cloud — overwriting newer cloud
   data made on another device.
3. **Failed read + empty disk (fresh hosted container) → the first user action
   overwrites cloud.** The read failure is treated as "no workspace blob". Autosave is
   blocked, but the first user-action save (e.g. saving a league, `fantasy_edit`)
   bypasses the block and the cloud check, and writes a near-empty session over the
   real cloud blob.
4. **A genuinely new hosted workspace** (cloud says "not found") cannot autosave until
   a user-action save happens. In practice `page_change` covers it, so this is a
   nuisance rather than data loss.

Findings 2 and 3 are data-loss risks. Neither was reproduced against the live store;
they follow from the code paths above.

## Proposed fix

1. **Typed read result.** Add
   `load_cloud_full_session_status(app_id) -> CloudRead(state, updated_at, status)` with
   `status ∈ {"ok", "not_found", "error", "disabled"}`. "not_found" only when the store
   answered and there is no row/blob; any exception is "error". Keep
   `load_cloud_full_session` as a thin wrapper so other callers are unchanged.
2. **On "error", never write cloud.** In `sync_workspace_protocol`, set
   `_suite_cloud_read_failed` (session-lived, not per run). While it is set:
   * `_cloud_autosave_blocked_reason` returns `"cloud_read_failed"` for **every**
     reason, including the user-action bypass list;
   * the disk blob may be shown, but is not fingerprinted as the restored cloud state;
   * show one warning: "Couldn't reach your saved data. Changes are kept in this session
     and will not be saved to your account until the connection returns."
3. **Retry with backoff.** Retry the read on later runs (e.g. 5 s, 15 s, 60 s). On "ok",
   clear the flag and run the normal first-sync path (cloud is authoritative for a
   session that never read it). Session edits made during the outage are offered as a
   download rather than silently merged.
4. **"not_found" on hosted** = new workspace: allow autosave without waiting for a
   user-action save (same rule the local install already uses).

## Tests to add with the fix

* `load_cloud_full_session_status` returns "error" when the storage call raises,
  "not_found" for no row, "ok" with the blob.
* Sync with read "error" and an older disk blob: `save_workspace_now(reason="fantasy_edit")`
  does not call `save_cloud_full_session`; the disk write still happens.
* Sync with read "error" and empty disk: no cloud write for any reason.
* Read recovers on retry: the flag clears, the cloud blob is applied, and cloud writes
  resume.
* Hosted "not_found": autosave writes on the first change.
* Regression: a normal hosted session (read "ok") saves exactly as today.

All of these can run against a fake storage module (the shape `suite_cloud_state`
already imports through `_import_storage`); a final check against the real store needs
staging credentials.

## What is implemented (quality/shared-functions)

The state a session can be in, and what each state may do:

| State | How it is recognised | Cloud writes |
|---|---|---|
| Cloud disabled (local install) | `CLOUD_READ_DISABLED` | none (disk only, unchanged) |
| Confirmed current data | read `ok`; the saved copy was applied, or the session synced earlier | allowed |
| Successful read, no saved data | read `not_found` (no row or empty blob) | allowed: nothing can be overwritten |
| Failed or unavailable read | read `error` (exception, timeout, permissions, malformed row) | **refused for every reason**, including user-action saves |
| Recovered, but never loaded the saved data | read answers after an `error` and the session was never reconciled | refused until the saved copy is re-applied as a first sync; outage edits are not trusted |

Implementation:

- **`suite_cloud_state`**
  - `load_cloud_full_session_status` returns a `CloudRead` with a status.
    `load_cloud_full_session` keeps its old return values for existing callers.
  - Any failed read sets `_suite_cloud_read_failed`.
  - `save_cloud_full_session` refuses while that flag is set, and records
    `_suite_cloud_write_blocked`.
  - `mark_cloud_reconciled` clears the flag. Only the workspace sync calls it, so another
    module's successful read cannot unlock writes for a session that never loaded its data.
- **`suite_user_persistence.sync_workspace_protocol`**
  - On a failed read it applies nothing: no stale disk copy.
  - It retries with backoff (5 s doubling to 60 s).
  - On recovery it restores the saved copy before anything can be written.
  - It marks the session reconciled only after a read the store answered.
- **`baseball_persistent_state`**: an unresolved failure forces the sync to run, so the warm
  startup skip can't leave saves paused for the rest of the session.
- **User copy**: `show_persistence_messages` tells the user their saved data isn't loaded and
  that changes won't be saved until the connection is back (`ui_user_copy.CLOUD_READ_FAILED_WARNING`).

Tests: `tests/test_hosted_autosave_reliability.py` uses a fake storage backend. It covers:
- read classification and the unchanged legacy tuple;
- writes refused until the session is reconciled;
- a stale disk copy is not applied;
- the destructive empty-disk save is blocked;
- recovery restores the saved copy, then saves resume;
- the retry backoff;
- a transient failure after a good sync;
- a confirmed-empty new workspace can save;
- the user warning, and the warm-skip guard.

On the previous code, the stale-disk and empty-disk scenarios fail: the stale copy was
applied, and the near-empty session was written to the cloud.

## Still to do

1. **Stale tab (optimistic concurrency).** Before writing, compare the cloud `updated_at` with
   the version this session applied or last wrote, and refuse if the cloud is newer.
   - Not built, because today the session records its own writes with the *local* clock
     (`_utc_now_iso()` after `save_cloud_full_session`). Comparing that with server timestamps
     would produce false conflicts or miss real ones.
   - It needs `save_current_state` to return the server's `updated_at`. That is a
     storage-layer change, to be verified on staging.
2. **Hosted "not found" autosave** (step 4 above). New workspaces still wait for a
   user-action save (unchanged).
3. **Staging acceptance.** These need credentials; they can't be done honestly with fakes:
   - against a staging Supabase project, block network access to the store mid-session and
     confirm no write happens, the warning shows, and recovery restores the saved copy;
   - repeat on a fresh container (empty disk).
