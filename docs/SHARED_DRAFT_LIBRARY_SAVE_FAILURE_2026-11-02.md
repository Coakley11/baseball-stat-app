# Shared Draft: Saved Draft Library save refused (2026-11-02, hosted `bc74759`)

**Error shown:** "Couldn't save this draft: cloud storage did not accept the save (stale_or_unhydrated_cloud_revision). It is still open here, so you can try again."

**Draft type:** a Shared Live Draft, completed (Library save is offered only after a draft finishes).

## Evidence (owner's read-only queries and export)

| Source | Result |
|---|---|
| Shared room `da9e78` (masked) | `status` and `room_status` both complete; revision 11; **picks_on_board 4 = total_picks 4**; participants 2; commissioner set; updated 2026-11-02 21:19:48 UTC |
| Owner's export `live_draft_board.csv` | 4 picks: Danny: Matt Olson; Barry: Cal Raleigh; Barry: Pete Alonso; Danny: Salvador Perez |
| Workspace row `baseball` (owner `daniel`) | 4 Library drafts; last updated **18:42:30 UTC** |
| Workspace row `baseball__712986` | 4 Library drafts; last updated **18:48:25 UTC** |

### Established
- The room is complete in storage, and its pick count matches the export (4 of 4).
- **Not yet established:** that the stored picks are those exact four players and teams. That needs a comparison against the stored board.
- The failed action writes only the account workspace, where the Saved Draft Library lives (`draft_archive_ui._execute_live_draft_save` → `_persist_archive` → `force_save_baseball_state`). It does not write the shared room, so it cannot have damaged the room.
- The completed draft is not in either workspace's Library: the counts are unchanged at 4.

### Inferred, to confirm
- **No successful workspace write after 18:42 / 18:48 UTC,** although the draft ran until 21:19 UTC. A live draft autosaves repeatedly, so this tab's workspace saves were very likely being refused for about 2.5 hours. Autosave refusals are silent; only the explicit Library save showed an error. Anything else changed in that period, such as queue or settings, may also not be in cloud storage.
- **Most consistent cause: B.**
  1. This tab's own write at about 18:42 succeeded.
  2. The read-back that records the new revision failed (`suite_cloud_state.py:660-666`).
  3. The tab kept its older revision, so every later save looked stale against its own write.
- **Cause A is also possible** if another tab or device on the same account and workspace wrote at 18:42. Owner to confirm whether one was open.
- **Cause C (never hydrated)** is unlikely for a tab that saved earlier in the session.

## Owner clarification and follow-up checks (2026-11-02)

- **Browsers were separate accounts.** Browser A was signed in to the owner's account; Browser B to Barry's separate account. Each account writes its own workspace record (`baseball` vs `baseball__<workspace>`), so Browser B could not have advanced the owner's workspace revision. That makes **cause B** (own write, then a failed revision re-read) more plausible.
- **Cause A is not yet ruled out:** another tab or device on the owner's own account could still have written.
  - **Check (read-only):** the owner's Baseball activity events by 5-minute bucket, page and event, from 18:00 to 21:30 UTC. Activity on another page at the same time suggests a second tab.
  - **Limit:** events carry no browser or device marker, so this can suggest but not prove a second writer.
  - **Gateway logs** can show write timing to `suite_app_current_state`. All requests come from the app server, so they cannot tell browsers apart either.
- **Pick identities:** only the room's pick count (4 of 4) has been compared with the export so far. The individual picks have not; a read-only query lists the stored board for that one room.

### Added to the Stage B candidate's required tests
- Two separate accounts in the same Shared Draft cannot change each other's workspace revision or Saved Draft Library, including when both save at once.
- Per-workspace revision tracking: the seen revision is stored per cloud record (`app` key), never shared across records.
- End-to-end stale-save recovery for a Library save: refused, rebased onto the fresh copy, saved; and a successful own write whose re-read fails.
- A visible warning when autosaves are being refused.

## Handling
- **No change to production:** the completed room and the existing Library entries are left untouched.
- **Separate persistence issue:** the Library save failure is tracked on its own. The fix candidate reuses Stage B's merge-on-stale (`fix/cloud-restore-hydration`, `5a09c4b` / `fa4d79b`, `workspace_merge.py`).
- **Additions the candidate needs:**
  - the seen revision scoped to the workspace record;
  - an end-to-end stale → rebase → save test for Library saves;
  - recovery from an own write whose re-read failed;
  - unhydrated saves still refused;
  - split error messages;
  - a visible warning when autosaves are being refused, rather than failing silently.
