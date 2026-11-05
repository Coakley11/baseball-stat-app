# Existing test failures on `dev` (`4d1e0be`) relevant to Shared Drafts, isolation, sync and invites

Regression scope: the 186 test files that touch invites, Shared Leagues, storage, recovery, the Library page,
Shared Draft rooms, sync or room codes.

| Run | Result |
|---|---|
| `dev` `4d1e0be` | 100 failed, 2 file-level errors |
| `fix/shared-draft-invites-dev` `bbbb0aa` | same 100 failed, same 2 errors; 1 more test passes (the invitee lookup test); 0 new failures |

63 of the 100 are in the relevant areas. Each was re-run alone on a clean `dev` worktree.

## Inspected: outdated tests (the behavior changed on purpose)

| Tests | Why it fails |
|---|---|
| `test_live_draft_room_code_visibility` (5) | The room code is still shown, waiting room and active draft. The separate Copy button and `st.code` were removed on purpose (`render_draft_room_code_panel`: "Intentionally no duplicate st.code, no Copy button"). |
| `test_live_draft_multiplayer_sync::test_guest_does_not_run_timer_autopick` | A guest may take over auto-pick through the timer lease when the host stalls (`472d56c`, "Stop Shared picks freezing at 0:00"). |
| `test_live_draft_acceptance_blockers::test_unsigned_does_not_restore_shared_membership` | Deliberate soft-offline: a briefly signed-out browser keeps its own room code, but the live room is dropped so it cannot pick. Nothing from another account. |
| `test_coakley11_workspace_ownership_e2e::test_join_room…`, `test_mp_identity_workspace_clamp` | Source-text checks: `join_shared_draft_room` mentions the workspace keys only to read them for diagnostics. It writes neither. |
| `test_ami_assistant_fantasy::test_another_managers_team_private_data_is_refused` | All five private tools refuse correctly. The failing line expects week 30 of a season starting 2026-04-06 to be "upcoming", and on 2026-11-05 it has started. The test depends on the calendar date. |
| `test_live_draft_progress` (2 of 3: not started) | A not-started room is still "not complete"; it now reports pick 1 as the next pick where the test expected none. |
| `test_shared_draft_two_client_flow::test_guest_join_rebuilds_local_pool…` | The guest's pool is found on the server's local pool file first (same server), so a rebuild is not needed. |
| `test_draft_room_participant_privacy`, `test_draft_room_context::test_private_queue_isolated…` | The isolation asserts pass (host and guest keep separate queues). The `KeyError` is on a renamed internal storage layout. |
| `test_draft_archive_visibility::test_team_claim_without_invite_stays_hidden` | No shared store in the test, so the stored league is "missing" and the copy counts as not shared: the security layer's rule. With the stored league present (production), the copy is refused. Recorded edge case: a copy whose shared record is missing stays visible to its holder. |
| `test_live_draft_shared_league` (2) | Expect the old title "Shared League Saved"; the message is "**League** saved. Your team: …". |
| `test_live_draft_shared_league_origin_visibility` (2) | The fixture draft is incomplete, so creation is refused before origin is tested. The same behavior is covered by `test_shared_league_create_accept_reliability`. |
| `test_fantasy_league_invites::test_resolve_invitee_target…` | Patches a function removed in `57009b3`; fixed on the branch. |

## By message: very likely outdated (not inspected one by one)

- **Renamed patch targets or widgets:** `test_live_draft_acceptance_blockers` (2), `test_live_draft_room_ux` (1), `test_coakley11…clamps_before_scoped_load` (`_FakeSt.query_params`), `test_pre_draft_shared_room` (2, widget key `live_draft_join_team_pick`).
- **Wording:**
  - `test_draft_room_join_trace::test_auth_diagnostics…` expects "log in"; the copy says "Sign in".
  - `test_draft_room_create_verify` expects "no active shared draft room was found"; the copy says "room code not found".
- **New setup validation:** `test_live_draft_resumable_ops`, `test_live_draft_resume_replace_consistency` (fixture picks per team).
- **The security release's "propose from your own team" rule:** `test_trade_offer_inbox_dismissals` (6).
- **Layout:** recommendation-card tests in `test_live_draft_multiplayer_poll`, `test_live_draft_decision_panels`, `test_live_draft_polish`.

## Not resolved by inspection: confirm in the QA two-account run

These could be genuine. The QA scenarios cover the same behavior end to end.

| Tests | Symptom | QA scenario |
|---|---|---|
| `test_live_draft_two_account_phase_closure` (2) | After a refresh the guest's team is blank; the guest's pick fails with "No players available" (the tests bypass page rendering, where the pool is normally ensured) | 8, 9 |
| `test_live_draft_progress::test_fresh_shared_room_is_not_complete` | A fresh shared room reports complete (fixture: a 1-player pool for 2 picks) | 1, 8 |
| `test_fantasy_league_invite_trade_e2e`, `test_shared_league_startup_reboot_e2e` | Cross-account trade not found after accept or reboot (0 ≠ 1) | 6, 9 |
| `test_global_fantasy_settings`, `test_imported_shared_league` | My team blank where `Daniel` was expected | 2, 11 |
| `test_draft_room_join_trace` (2), `test_draft_room_context` sync (2) | The join does not activate multiplayer in the trace; sync reload counts | 10, 8 |
| `test_shared_draft_two_client_flow` (3: start timer, persist-wipe retry, save-continue rejoin) | Host timer arming; retry counts; rejoin reason text | 8, 9 |
| `test_validate_participant_may_draft`, `test_simulator_resume_account_isolation`, `test_live_draft_create_and_mode_sticky`, `test_draft_queue_controls_simplify`, `test_draft_ui_multiplayer`, `test_fantasy_trade_center_workflow` | Single assertions on draft-complete or mode or queue state | 8, 9 |

None of these changed between `dev` and the branch.
