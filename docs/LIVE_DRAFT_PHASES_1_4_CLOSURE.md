# Live Draft Phases 1–4 — Closure Matrix

**Baseline:** `7ac0c9b` (workflow header + identity recursion hotfix)  
**Last updated:** 2026-07-13  
**Scope:** Phases 1–4 only — Phase 5 deferred.

## Summary

| Phase | Complete | Partial | Missing / Deferred |
|-------|----------|---------|-------------------|
| 1 — Unified draft action | 1 | 0 | 0 |
| 2 — Unified draft UI | 1 | 0 | 0 |
| 3 — Multiplayer / shared league | 8 | 1 | 0 |
| 4 — Live Draft UX | 22 | 1 | 0 |
| Cross-cutting (hotfixes) | 6 | 0 | 0 |

**Deferred (explicit, not Phase 5 work):** WebSocket realtime (polling acceptable for v1), private AMI Q&A per user, invite-link permissions polish.

---

## Phase 1 — Unified `draft_player` core action (`f153885`)

| # | Requirement | Original behavior | Status | Files / functions | Automated tests | Live verified | Remaining work |
|---|-------------|-------------------|--------|-------------------|-----------------|---------------|----------------|
| P1-1 | Single draft action | One `draft_player()` validates turn, writes board/live state, cleans queue, syncs | **complete** | `draft_actions.py` — `draft_player`, `can_draft_player` | `tests/test_draft_actions.py` | no | — |
| P1-2 | Source routing | Supports simulator, queue, live queue sources | **complete** | `draft_actions.py` — `DRAFT_SOURCES` | `tests/test_draft_actions.py` | no | — |

---

## Phase 2 — Unified draft UI (`75e2925`)

| # | Requirement | Original behavior | Status | Files / functions | Automated tests | Live verified | Remaining work |
|---|-------------|-------------------|--------|-------------------|-----------------|---------------|----------------|
| P2-1 | `render_draft_button` | Shared Draft/Queue buttons across pages | **complete** | `draft_ui.py` — `render_draft_button` | `tests/test_draft_live_handoff.py` | no | — |

---

## Phase 3 — Simple Live Draft Room / multiplayer

| # | Requirement | Original behavior | Status | Files / functions | Automated tests | Live verified | Remaining work |
|---|-------------|-------------------|--------|-------------------|-----------------|---------------|----------------|
| P3-1 | Room code + join | Create/join shared room with team claim | **complete** | `draft_room_context.py`, `live_draft_setup_mode.py` | `tests/test_pre_draft_shared_room.py` | yes (Robins Fantasy) | — |
| P3-2 | Shared board sync | Picks propagate via shared store + revision | **complete** | `draft_room_shared_state.py`, `commit_shared_room_state` | `tests/test_multiplayer_draft_acceptance.py` | yes | — |
| P3-3 | Shared clock | Timer visible to all participants | **complete** | `live_draft_timer_ui.py`, `live_draft_on_clock_ui.py` | `tests/test_live_draft_room_ux.py` | yes | — |
| P3-4 | Completion → shared league | Completed live draft saves to library | **complete** | `live_draft_shared_league.py`, `draft_archive_ui.py` | `tests/test_live_draft_shared_league.py` | yes (Robins Fantasy) | — |
| P3-5 | Origin / badge correctness | Live Draft vs Imported League badges | **complete** | `fantasy_league_context.py`, `fantasy_creation_origin_repair.py` | `tests/test_creation_origin_repair.py`, `tests/test_coakley11_live_draft_badge.py` | yes | — |
| P3-6 | Active library coherence | No hybrid archive/context cards | **complete** | `saved_draft_library_selection.py`, `draft_archive_ui.py` | `tests/test_saved_draft_library_active_selection.py` | yes | — |
| P3-7 | Draft Assistant board resolution | Completed draft shows 20/20, no NameError | **complete** | `draft_assistant_board.py`, `draft_room_state.py` | `tests/test_draft_assistant_board_resolution.py` | yes (Daniel/Coakley11) | — |
| P3-8 | Workflow header coherence | Headers match persisted Robins Fantasy context | **complete** | `fantasy_context_source.py`, `fantasy_workspace_team_identity.py` | `tests/test_fantasy_workflow_header_coherence.py` | yes | — |
| P3-9 | Identity recursion guard | Saved Draft Library opens without RecursionError | **complete** | `fantasy_workspace_team_identity.py`, `suite_identity_guard.py` | `tests/test_fantasy_workspace_team_identity_recursion.py` | yes | — |
| P3-10 | Realtime transport | WebSocket / Supabase realtime | **partial** | Polling + refresh (`poll_shared_draft_room`) | `tests/test_shared_draft_context.py` | yes (acceptable v1) | **Deferred:** true push realtime is Phase 5 |

---

## Phase 4 — Live Draft UX (`960ac86` + closure work)

| # | Requirement | Original behavior | Status | Files / functions | Automated tests | Live verified | Remaining work |
|---|-------------|-------------------|--------|-------------------|-----------------|---------------|----------------|
| 1 | Team identity consistency | Canonical user / team / role labels | **complete** | `live_draft_ux.py` — `format_participant_identity` | `tests/test_live_draft_ux.py` | yes | — |
| 2 | Team assignment display | “Your Fantasy Team” / “You are managing …” | **complete** | `live_draft_ux.py` — `format_your_fantasy_team` | `tests/test_live_draft_ux.py` | yes | — |
| 3 | Commissioner / status summary | Draft status summary card | **complete** | `live_draft_room_ui.py` — `render_draft_status_summary_card` | `tests/test_live_draft_room_ux.py` | yes | — |
| 4 | Lobby UI | Join checklist, ready state | **complete** | `live_draft_setup_ui.py` | `tests/test_pre_draft_shared_room.py` | yes | — |
| 5 | Draft start flow | User-facing steps only | **complete** | `live_draft_start_progress.py`, `live_draft_ux.py` | `tests/test_live_draft_start_progress.py` | yes | — |
| 6 | Draft control center | Primary Pause/Resume; advanced expander | **complete** | `streamlit_app.py` Live Draft section | `tests/test_live_draft_room_ux.py` | yes | — |
| 7 | Collapse lobby after start | Hide join code during picks | **complete** | `live_draft_room_ui.py`, `streamlit_app.py` | `tests/test_live_draft_room_ux.py` | yes | — |
| 8 | Recommendation card strengths | Natural-language strengths | **complete** | `live_draft_ux.py` — `describe_strengths` | `tests/test_live_draft_ux.py` | yes | — |
| 9 | Recommendation confidence | Star rating + label | **complete** | `live_draft_ux.py` — `confidence_label_from_score` | `tests/test_live_draft_ux.py` | yes | — |
| 11 | Scarcity explanation | Tier-1 counts + drop-off picks | **complete** | `live_draft_ux.py` — `format_scarcity_explanation` | `tests/test_live_draft_ux.py` | yes | — |
| 12 | Fantasy Edge tooltip | ⓘ with explanation | **complete** | `live_draft_rec_badges.py`, `streamlit_app.py` | `tests/test_live_draft_rec_badges.py` | yes | — |
| 13 | Roster Fit tooltip | Category/slot explanations | **complete** | `live_draft_rec_badges.py` | `tests/test_live_draft_rec_badges.py` | yes | — |
| 14 | Team needs visualization | Star-weighted category needs | **complete** | `live_draft_category_outlook.py`, `live_draft_room_ui.py` | `tests/test_live_draft_decision_panels.py` | yes | — |
| 15 | Draft button labels | 🔴 Draft / ⭐ Queue | **complete** | `draft_ui.py`, `live_draft_room_ui.py` | `tests/test_live_draft_room_ux.py` | yes | — |
| 16 | Queue drag-and-drop | Sortable queue + ↑/↓ fallback | **complete** | `draft_ui.py` — `render_live_draft_queue_panel` | `tests/test_live_draft_room_ux.py` | yes | — |
| 17 | Recommendation sorting | Sort by score columns | **complete** | `live_draft_ux.py` — `sort_recommendation_table` | `tests/test_live_draft_ux.py` | yes | — |
| 24 | Draft animations | Pick card, board slide, on-clock flash | **complete** | `live_draft_ux.py`, `live_draft_on_clock_ui.py`, `draft_actions.py` | `tests/test_live_draft_ux.py` | no | Live-verify animation once per pick |
| 25 | Position color coding | Historical Explorer palette | **complete** | `live_draft_ux.py` — `POSITION_COLORS`, `inject_position_color_styles` | `tests/test_live_draft_ux.py` | yes | — |
| 29 | Survival probability | Real % not 1.000000 | **complete** | `live_draft_pick_scoring.py`, `live_draft_ux.py` | `tests/test_live_draft_recommendations.py` | yes | — |
| 32 | OF slot eligibility copy | “Eligible for N remaining OF spots” | **complete** | `live_draft_ux.py` — `format_of_slot_eligibility` | `tests/test_live_draft_ux.py` | yes | — |
| 33 | Top strengths wording | Scouting descriptions | **complete** | `live_draft_ux.py` — `describe_strength` | `tests/test_live_draft_ux.py` | yes | — |
| 34 | Shared room summary | Compact status card w/ code | **complete** | `live_draft_room_ui.py` — `render_draft_status_summary_card` | `tests/test_live_draft_room_ux.py` | yes | — |
| DA | Draft Assistant sync | Live draft drives assistant pool/needs | **complete** | `draft_assistant_board.py`, `fantasy_context_source.py`, `live_draft_ui_cache.py` | `tests/test_draft_assistant_board_resolution.py` | yes (completed Robins Fantasy) | — |

---

## Cross-cutting hotfixes (post-Phase 4, on `7ac0c9b`)

| Item | Status | Tests | Live |
|------|--------|-------|------|
| Upload Test Demo stays Imported / inactive | complete | `tests/test_creation_origin_repair.py` | yes |
| Robins Fantasy canonical IDs preserved | complete | `tests/test_saved_draft_library_active_selection.py` | yes |
| Daniel→Donny, Coakley11→Team B | complete | `tests/test_coakley11_live_draft_badge.py` | yes |
| Quick Guide no literal `</div>` | complete | `tests/test_page_guide_markup.py` | yes |
| Developer diagnostics hidden by default | complete | manual | yes |
| Origin repair gated per session | complete | `tests/test_saved_draft_library_active_selection.py` | n/a |

---

## Two-account acceptance scenario

Automated: `tests/test_live_draft_two_account_phase_closure.py`  
Live: Daniel creates/opens Robins Fantasy room → Coakley11 joins Team B → alternating picks → pause/resume → completion → library persistence → refresh/sign-out preserves identity.

---

## Performance (closure pass)

| Scenario | Before (uncached repair/descriptor) | After | Goal |
|----------|-------------------------------------|-------|------|
| `resolve_fantasy_workflow_source_descriptor` warm (2nd call) | ~full resolve each rerun | cached hit (<1 ms in unit test) | <50 ms |
| Saved Draft Library origin repair | every library render | once per session (`_creation_origin_repair_done`) | not on harmless rerun |
| Live Draft timer tick | recommendation rebuild risk | fragment banner `flash=False` on tick | timer-only <1 s |

Full page profiling on Streamlit Cloud remains manual; instrumentation via `live_draft_perf.py` and `page_perf_phases.py`.

---

## Known limitations

1. **Req 24 animations** — automated once-per-pick guards exist; live animation timing depends on Streamlit rerun cadence.
2. **P3-10 realtime** — polling/refresh, not WebSocket (explicitly deferred).
3. **Performance goals** — warm navigation targets require production measurement; local unit tests cover cache invalidation only.

---

## Test command (single process)

```bash
python -m pytest \
  tests/test_draft_actions.py \
  tests/test_draft_live_handoff.py \
  tests/test_pre_draft_shared_room.py \
  tests/test_multiplayer_draft_acceptance.py \
  tests/test_live_draft_shared_league.py \
  tests/test_live_draft_ux.py \
  tests/test_live_draft_room_ux.py \
  tests/test_live_draft_recommendations.py \
  tests/test_live_draft_rec_badges.py \
  tests/test_live_draft_start_progress.py \
  tests/test_live_draft_decision_panels.py \
  tests/test_live_draft_draft_flow.py \
  tests/test_draft_assistant_board_resolution.py \
  tests/test_creation_origin_repair.py \
  tests/test_fantasy_workflow_header_coherence.py \
  tests/test_fantasy_workspace_team_identity_recursion.py \
  tests/test_saved_draft_library_active_selection.py \
  tests/test_saved_draft_library_identity_guard.py \
  tests/test_coakley11_live_draft_badge.py \
  tests/test_page_guide_markup.py \
  tests/test_live_draft_perf.py \
  tests/test_live_draft_two_account_phase_closure.py \
  -q
```
