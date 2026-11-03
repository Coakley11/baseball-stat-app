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

## Owner's read-only audits (2026-11-02)

### Library deletion markers (`library_deletion_markers.sql`)
| Workspace | Current entries | Live Draft without owner | Deletion markers | Markers with a Live Draft save event |
|---|---|---|---|---|
| Main | 4 (3 Live Draft, 1 imported) | 0 | 2 | 0 |
| Older | 3 (2 Live Draft, 1 imported) | 0 | 2 | 1 (last saved 2026-07-12) |

- A marker does not prove the clean-up bug deleted anything: a deliberate delete leaves the same marker.
- No ownerless Live Draft entries exist now, so nothing is currently at risk from the clean-up.
- Nothing was deleted, restored or changed.

### Completed room `da9e78` (`room_recovery_inputs.sql`)
- **Room:** complete, revision 11, 4 of 4 picks, 2 participants.
- **Teams:** Danny and Barry, 2 rounds of 2 picks each.
- **League:** My Fantasy League, 5x5 Roto, scoring Roto (5x5), roster slots C and 1B, 2 players per team.
- **Commissioner:** Danny.
- **Picks match the owner's CSV** in order, team and player id: Danny olsonma02, Barry raleica01, Barry alonspe01, Danny perezsa02.
- **Not checked:** player names and positions are not stored on the board rows the query read.

### Commissioner ids differ: expected
In the hosted app the sign-in (Auth) user id and the suite account id are different values:
- **Participant key:** the Auth id (`resolve_participant_id` with sign-in on).
- **`host_user_id`:** also the Auth id (`draft_room_context`: `auth_user_id(session)`).
- **Participant record `user_id` / `account_user_id`:** the suite account id (`_participant_account_identity`: `get_account_user_id()`).

The masked commissioner key therefore matches the host, while the record's account id differs. That is by design, not a mapping error.

**Consequence found:** the deployed security release compared league records, which store the suite id, with the Auth id only. A real commissioner was not recognised as commissioner. Fixed on `hotfix/keep-live-draft-saves` (`c2d6341`): a stored id matches either of the session's own two ids.

**Stage B recovery:** matches the participant key (Auth id) and the host id, so it recognises both seats. Before deployment, it should also accept the suite id on the participant record.

