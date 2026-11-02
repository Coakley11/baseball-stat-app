# Shared Draft: guests stuck in the lobby after Start

Branch `fix/shared-draft-lobby-start-sync`, fix commit `7e4391d`, based on `origin/dev` `50c3e9b`.
Local only: not pushed, merged or deployed. Separate from the Shared Draft UI work.

## The defect (hosted app, 2026-11-02)

- **What happened:** Browser A (commissioner) created a room, Browser B joined, and A started the draft. B stayed in the waiting room, through automatic polling and through a browser refresh.
- **What Supabase held:** the room as `in_progress`, revision 8. The column and the document agreed.

## Root cause

1. **The Supabase head probe returned no live-room fields.**
   - The poller compares a cheap head probe with the session. If the revisions match, `_shared_head_live_fields_diverge` still reloads when the room status, pick index or timer deadline differ.
   - The local-file store's head carries those fields.
   - `SupabaseSharedRoomStore.load_head` selected only `room_code, revision, status, updated_at`. So in production that safety net never fired, while every test, which runs on the local store, passed.
2. **The lobby refresh advanced the session revision over a failed apply.**
   - `refresh_shared_lobby_authority` re-bound `draft_room_shared_meta.revision` to the stored revision even when publishing the newer room raised an exception (swallowed) or returned `None`.
   - After that, every poll saw "no change".
   - The meta is also persisted in the workspace (`baseball_persistent_state.py`), so a browser refresh restored the same state.
3. **Not related to the containment.** All room I/O uses the service-role path. Create and join worked after Step B, and the probe request itself succeeds.

## The change (`draft_room_context.py`, `draft_room_supabase_store.py`; +81 / −12)

- **Head probe:**
  - It projects `room_status`, `current_pick_index` and `timer_deadline` out of `shared_room_json` (the `room` object, else legacy `live_room`) with PostgREST JSON paths, the same style as the existing chat probe.
  - The keys match the local store's `extract_live_head_fields`.
  - It never downloads the whole document.
- **Lobby refresh:** the session revision advances only when the newer room applied (the publish returned a room) or the session already holds that revision.
- **Traffic bound:**
  - A same-revision difference triggers one full load.
  - The same remote head (revision, status, pick index and deadline) cannot trigger another for `HEAD_DIVERGE_RELOAD_SEC = 30`.
  - A new remote deadline is a new head, so it loads immediately.

## Traffic and timer review

| Case | Before (production) | After |
|---|---|---|
| Room unchanged | head probe only | head probe only (about 6 extra small fields per probe) |
| Revision advanced | full load | full load (unchanged) |
| Same revision, guest stale (this defect) | **never reloaded** | one full load, then normal |
| Same revision, timer write that keeps the revision | **never synced** | one full load per new deadline |
| Local room stays different after the load | n/a (check inactive) | at most one full load per 30 s, not every 2.5 s poll |

- **Room sizes:** stored rooms are 46 KB to 988 KB (preflight D4). The bound keeps a stubborn mismatch to about one full room per 30 s for that one session. In practice the first load resolves the mismatch.
- **Timer authority:** the host saves deadline repairs to the room (`live_draft_timer_ui.py`, `commit_shared_room_state` when `is_room_host` and `multiparty_may_run_autopick`).
- **Unsaved deadlines:** the only unsaved local deadline is the on-clock painter's one-time arm when no deadline exists yet (`live_draft_on_clock_ui.py`). In that case the stored deadline replaces it, at most every 30 s. For guests that is the intended behaviour ("guests must poll the authoritative deadline, never invent one").
- **Live check:** watch the host clock for 2–3 picks during the test after the deploy.

## Tests

- **New:** `tests/test_shared_draft_lobby_start_sync.py`, 15 tests, all pass. 8 of them fail on the original code.
  - Supabase-shaped probe: the real `load_head` with a fake `_request` that answers the projection.
  - Automatic polling, on both store types.
  - Manual refresh, with a restored session at the current revision.
  - Failed apply, both ways it can fail.
  - The traffic bound, and a new remote deadline loading immediately.
- **Existing (39 files):** the Shared Draft, room, lobby, poll, room-code, guest-join, timer, autopick and expired-pick suites.
  - **324 passed, 33 failed.**
  - The same 33 fail identically on an untouched `origin/dev` `50c3e9b` checkout, so there are **no new regressions**.
  - The first draft of the fix broke `test_unchanged_revision_still_syncs_timer_deadline`, and the final version passes it.

### The 33 baseline failures (fail identically on origin/dev 50c3e9b)

These are stale or environment-sensitive tests, not caused by this change. Examples:

- the shared sample fixture's three placeholder board rows count as picks (`3 != 1`);
- the recommendation-card layout name was renamed (`horizontal_grid_3`);
- autopick and timer tests are order-dependent (`test_queue_does_not_override_configured_rule` passes alone and fails in its file on both trees);
- room-code panel markup changed.

| File | Test |
|---|---|
| `test_draft_room_context.py` | `DraftRoomContextTests::test_private_queue_isolated_per_participant` |
| `test_draft_room_context.py` | `DraftRoomContextTests::test_sync_shared_room_refreshes_runtime` |
| `test_draft_room_context.py` | `DraftRoomContextTests::test_sync_skips_full_load_when_revision_unchanged` |
| `test_draft_room_create_verify.py` | `DraftRoomCreateVerifyTests::test_join_reports_not_found_with_backend` |
| `test_draft_room_join_trace.py` | `DraftRoomJoinTraceTests::test_auth_diagnostics_when_not_signed_in` |
| `test_draft_room_join_trace.py` | `DraftRoomJoinTraceTests::test_join_records_trace_and_activates_multiplayer` |
| `test_draft_room_join_trace.py` | `DraftRoomJoinTraceTests::test_prepare_live_draft_state_preserves_shared_room` |
| `test_draft_room_json_sanitize.py` | `SharedRoomDocumentSanitizeTests::test_sanitize_shared_room_document_converts_live_room_blob` |
| `test_draft_room_participant_privacy.py` | `DraftRoomParticipantPrivacyTests::test_different_auth_accounts_isolated_in_same_room` |
| `test_draft_ui_multiplayer.py` | `DraftUiMultiplayerSmokeTests::test_reset_membership_button_does_not_raise` |
| `test_live_draft_autopick_no_queue.py` | `LiveDraftAutopickNoQueueTests::test_highest_legal_catcher_by_configured_rule` |
| `test_live_draft_autopick_no_queue.py` | `LiveDraftAutopickNoQueueTests::test_multiple_open_slots_picks_best_legal_any_slot` |
| `test_live_draft_autopick_no_queue.py` | `LiveDraftAutopickNoQueueTests::test_queued_player_not_selected_because_queued` |
| `test_live_draft_multiplayer_poll.py` | `RecCardRenderTests::test_recommendation_cards_use_compact_horizontal_layout` |
| `test_live_draft_multiplayer_sync.py` | `HostOnlyAutopickTests::test_guest_does_not_run_timer_autopick` |
| `test_live_draft_room_code_visibility.py` | `RoomCodeVisibilityTests::test_active_draft_path_has_single_copy_key` |
| `test_live_draft_room_code_visibility.py` | `RoomCodeVisibilityTests::test_header_shows_code_during_active_draft` |
| `test_live_draft_room_code_visibility.py` | `RoomCodeVisibilityTests::test_panel_renders_code_and_copy_button` |
| `test_live_draft_room_code_visibility.py` | `RoomCodeVisibilityTests::test_two_panels_with_different_prefixes_do_not_collide` |
| `test_live_draft_room_code_visibility.py` | `RoomCodeVisibilityTests::test_waiting_room_path_has_single_copy_key` |
| `test_live_draft_room_ux.py` | `TimerCountdownTests::test_on_clock_banner_html_includes_timer_element` |
| `test_live_draft_timer_expiration.py` | `AutopickIgnoresQueueTests::test_queue_does_not_override_configured_rule` |
| `test_live_draft_timer_expiration.py` | `ManualNearZeroTests::test_manual_pick_blocks_second_timer_pick` |
| `test_live_draft_timer_expiration.py` | `TimerExpirationAdvanceTests::test_expiration_processed_only_once` |
| `test_live_draft_timer_ui.py` | `LiveDraftTimerLiveReadyTests::test_first_live_paint_rearms_start_armed_expired_clock` |
| `test_live_draft_timer_ui.py` | `LiveDraftTimerLogicTests::test_render_timer_bar_mounts_recovery_fragment_when_expired` |
| `test_live_draft_timer_ui.py` | `LiveDraftTimerLogicTests::test_timer_should_not_run_during_start` |
| `test_pre_draft_shared_room.py` | `PreDraftSharedRoomAppTestLifecycle::test_guest_join_one_click_shows_success_and_same_room` |
| `test_pre_draft_shared_room.py` | `PreDraftSharedRoomAppTestLifecycle::test_guest_join_single_option_team_b_without_manual_toggle` |
| `test_shared_draft_two_client_flow.py` | `SharedDraftTwoClientFlowTests::test_guest_cannot_start_shared_draft` |
| `test_shared_draft_two_client_flow.py` | `SharedDraftTwoClientFlowTests::test_guest_join_rebuilds_local_pool_when_document_stripped` |
| `test_shared_draft_two_client_flow.py` | `SharedDraftTwoClientFlowTests::test_persist_wipe_retries_local_pool_rebuild` |
| `test_shared_draft_two_client_flow.py` | `SharedDraftTwoClientFlowTests::test_save_continue_two_client_rejoin_without_injected_markers` |

## Hosted deployment facts

- **Repository and branch:** Streamlit Cloud deploys `Coakley11/baseball-stat-app`, branch **`dev`**, entry point `streamlit_app.py`, Python 3.12, Streamlit 1.59.1 (README). **A push to `dev` is a deploy.**
- **Fast-forward:** `origin/dev` is `50c3e9b` (re-fetched 2026-11-02), the base of this branch, so `7e4391d` lands as a fast-forward.
- **Build marker:**
  - The app reports its build from `deploy_commit.txt`, which currently pins `f1fd67b`.
  - The repo's convention is a separate "Pin the Dev deploy marker…" commit (for example `7d381af`).
  - Without it, the hosted app keeps reporting the old marker.
- **Not included:** the UI work and any other branch (`ami/*`, the integration candidates, `bb-restore` docs). This deploy is these two files only.

## Pre-deployment verification (owner, 2026-11-02)

- **Stored JSON paths (SQL, read-only).** The test room `eddef3` has revision 8, `room->>status = in_progress`, `room->current_pick_index = 1`, `room->timer_deadline = 1793625199.554084`, and `live_room` null. The other two rooms are complete.
- **The exact PostgREST head projection (REST, read-only, publishable key).** The `select` was taken from `SupabaseSharedRoomStore.load_head` on this branch.

  | Request | Result |
  |---|---|
  | Exact select | HTTP 401, 42501: parsed, columns exist, refused by the Step B containment, no rows |
  | Control with broken syntax | 400 PGRST100 |
  | Control with a misspelled column | 400 42703 |

  The projection is valid and no room content was returned.
- **Approval.** The owner approved deploying this fix only to `dev`, with the deploy-marker commit.

## Pre-deployment check (read-only, owner runs in the SQL editor)

This confirms the JSON paths the new probe reads exist in stored rooms. It returns no room codes and no content.

```sql
select left(md5(room_code), 6) as room_label, revision,
       shared_room_json->'room'->>'status' as room_status,
       shared_room_json->'room'->'current_pick_index' as pick_index,
       shared_room_json->'room'->'timer_deadline' as timer_deadline,
       shared_room_json->'live_room'->>'status' as legacy_status
from public.baseball_shared_draft_rooms
order by updated_at desc
limit 3;
```

- **Expected:** `room_status = in_progress` for the test room (`eddef3`). `pick_index` and `timer_deadline` may be null before the first pick. `legacy_status` is normally null.
- **Rooms written by an older build:** if `room_status` is null but `legacy_status` is set, the probe's fallback covers that case.

## Deployment plan (each step needs the owner's explicit approval)

1. **Review:** `git -C C:/tmp/bb-sync-fix show 7e4391d`.
2. **Read-only check:** run the SQL above and confirm the paths.
3. **Pin the marker:** add one commit on this branch that pins `deploy_commit.txt` to `7e4391d`, following the repo convention.
4. **Re-confirm the base:** re-fetch and confirm `origin/dev` is still `50c3e9b`. If it moved, rebase the two commits onto it and re-run this test set before going on.
5. **Push:** `git push origin fix/shared-draft-lobby-start-sync:dev` as a fast-forward. Streamlit Cloud then redeploys.
6. **Confirm the build:** check that the hosted app reports `7e4391d` (the build marker).
7. **Two-browser test on the hosted app:**
   - Create, join and start the draft. B enters the draft within about 3–8 s with no refresh.
   - Refresh B mid-draft. It stays in the draft.
   - Make picks in both directions.
   - Watch the host clock for 2–3 picks: it must not jump or reset.
   - An existing room opens. A league and an invite open.
   - The stuck test room (`eddef3`) should recover on B's next poll.

## Rollback

- **Steps:** revert the two commits on `dev`, either by `git revert` with a new marker pin, or by fast-forwarding `dev` back to the previous build with the owner's approval. Push, and Streamlit Cloud redeploys.
- **No data involved:** no data, schema, RLS or permission change is part of this fix, so rollback involves no database step.
- **After a rollback,** guests can get stuck in the lobby again, as before.
