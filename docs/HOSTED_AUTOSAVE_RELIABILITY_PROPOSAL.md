# Hosted autosave reliability — audit and proposed fix (not implemented)

Status: proposal (Phase D, October 2026). Not built here because it changes the shared
cloud persistence path used by every suite app and can only be verified against the real
cloud store, which needs credentials this work did not have.

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
