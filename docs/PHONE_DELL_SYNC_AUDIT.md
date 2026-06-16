# Phone ↔ Dell Sync Audit Checklist

Goal: **one authoritative cloud-backed state** so a change on phone appears on Dell (and vice versa) without silent local-only drift.

Legend: **Cloud** = persisted via suite cloud / activity API · **Local** = session or browser only · **Partial** = cloud exists but gaps known · **Gap** = not synced today

---

## 1. Draft Room Simulator

| Item | Sync | Notes |
|------|------|-------|
| Draft board picks | Cloud | Canonical board via `draft_room_state` / workspace save |
| Team rosters (board) | Cloud | Derived from board rows |
| Player pool / rankings | Partial | Rebuilt from yearly + market data on each device |
| Draft queue | Cloud | `draft_queue` in workspace payload |
| Watchlist | Cloud | When saved to workspace |
| Sleepers list | Cloud | Page filters + workspace |
| AMI draft cache (`_ami_draft_snapshot`) | **Local** | Rebuilt on each device at send/render; metadata refreshed from board on send (v12) |
| Primary Position on roster | Partial | From pool engine; now cached in `user_roster_detail` / `roster_position_index` on send |

---

## 2. Draft Assistant Simulator

| Item | Sync | Notes |
|------|------|-------|
| Recommendations | **Local** | Recomputed from synced board + settings |
| AMI questions / insight cards | Cloud | Activity + context blob + resume key |
| `draft_pick_adjustment` | Cloud | Session setting in workspace |
| Board-linked pick/round | Cloud | `draft_board_summary_for_team` from canonical board |

---

## 3. Live Draft Room

| Item | Sync | Notes |
|------|------|-------|
| Active draft state | Cloud | `live_draft_room` blob |
| Timer / on-clock | Partial | Live room; needs active session on both devices |
| Draft settings | Cloud | Room config in live draft payload |
| Current pick / round | Partial | `slot.Round` + pick index; authoritative when page re-caches |
| Queue / watchlist | Cloud | Same as draft room when linked |

---

## 4. Baseball Insight

| Item | Sync | Notes |
|------|------|-------|
| Latest insight (`_ami_pending_insight`) | Partial | Insight store v10 + URL deep link; **newly created** instant cards need same-run render + cloud save (v19) |
| Dismissed insight IDs | Cloud | `_ami_dismissed_insight_ids` + dismissal saved items |
| Continue / full-analysis links | Cloud | Resume key + question_id in activity |
| Instant solve result | Partial | Staged immediately on submit (v19 preserve flag); cloud via activity + blob on send |

---

## v19 retest focus (Phone ↔ Dell)

| Target | Status | Notes |
|--------|--------|-------|
| Newly created insights | **Partial** | Activity + blob sync; instant card is same-run local until cloud hydrate |
| Dismissed insights | Cloud | `persist_insight_dismissal_to_cloud` |
| Watchlists / queue | Cloud | `draft_state` workspace block |
| Sleepers filters | Partial | `fantasy_state.sleepers.filters` in cloud; position multiselect was resetting (v19 fix) |
| Comparison state | Cloud | `comparison_state.players` canonical |
| Trend state | Cloud | `trend_state` canonical |
| Page restore | Cloud | `page_filter_state` per page |
| Workspace restore | Cloud | `baseball_workspace_state` envelope on save |
| AMI draft cache | **Local** | `_ami_draft_snapshot` rebuilt per device |
| Team roster positions | Partial | Resolved from yearly pool at send (v19); not stored on board rows |

---

## 5. Command Center

| Item | Sync | Notes |
|------|------|-------|
| Activities | Cloud | `record_activity` on non-duplicate send |
| Continue cards | Cloud | Resume upsert after blob save |
| Duplicate sends | **Gap** | Skips new activity if same `question_id` within window |
| Draft Room send path | Partial | Same sidebar as all pages; requires non-empty question + successful submit |

---

## 6. Workspace / Page Restore

| Item | Sync | Notes |
|------|------|-------|
| Current page | Cloud | Navigation state in workspace |
| Page filters / widgets | Cloud | Per-page state handlers |
| Active draft banner | Cloud | Live draft pointer in session |
| AMI warm pool cache | **Local** | Intentionally not synced; rebuilt from board |

---

## Known gaps (priority)

1. **AMI draft cache** is device-local — pick/round/positions refreshed from canonical board on every send (v12), but available-player pool is not cross-device shared.
2. **Duplicate question_id** suppresses Command Center activity — by design; change wording or wait for dedupe window to expire.
3. **Live draft round** on simulator pages — `build_context_from_session` no longer applies stale `live_draft_room` index unless on Live Draft page (v12).
4. **Recommendations** on Draft Assistant — recomputed per device; should match if board + settings match.

---

## Manual verification script

1. Phone: log 3 picks on Draft Room → save → confirm Dell board matches.
2. Phone: ask roster-needs question → Get Baseball Insight → confirm Command Center activity + insight card.
3. Dell: open same question via Continue → confirm round 4 at pick 8 (2-team league) and OF/SS/C labels.
4. Phone: dismiss insight → Dell refresh → confirm dismissal propagates.
5. Dell: change queue → Phone refresh → confirm queue order.

---

## Authoritative sources (v14)

| Field | Source |
|-------|--------|
| `current_pick` | `draft_board_summary_for_team` (simulator) or live `slot` index + 1 |
| `draft_round` | `summary.current_round` or `slot.Round` — refreshed on every send |
| Roster positions | `_ami_player_position_lookup` (full pool) + `user_roster_detail` + `roster_position_index` |
| Team review roster | `attach_draft_team_to_context` after finalize — board team column |

## v14 execution status

| Check | Status |
|-------|--------|
| Team review runs after finalize (no roster clobber) | Done |
| `refresh_draft_ami_metadata` pick/round only | Done |
| Team diagnostics on send (`requested_team`, etc.) | Done |
| Timing `at C for pick` player + position extraction | Done |
| `baseball_ami_pages.py` Trends/Sleepers/Comparison send hooks | Started |

---

## Sync matrix (Phone ↔ Dell)

| Feature | Phone→Dell | Dell→Phone | Status |
|---------|------------|------------|--------|
| **Draft Room Simulator** | | | |
| Board picks | ✓ | ✓ | Fully synced (cloud workspace) |
| Team rosters (board-derived) | ✓ | ✓ | Fully synced |
| Draft queue | ✓ | ✓ | Fully synced |
| Watchlist | ✓ | ✓ | Fully synced (when saved) |
| Recommendations | — | — | Local-only (recomputed per device) |
| AMI draft cache pool | — | — | Local-only (rebuilt at send) |
| Pick / round metadata | ✓ | ✓ | Fully synced (board authority on send) |
| Questions / insight cards | ✓ | ✓ | Fully synced (activity + blob) |
| **Draft Assistant Simulator** | | | |
| Draft state (board-linked) | ✓ | ✓ | Fully synced |
| Recommendations | — | — | Local-only |
| Insights / continue links | ✓ | ✓ | Fully synced |
| **Live Draft Room** | | | |
| Timer / on-clock | Partial | Partial | Partial (active session required) |
| Current pick / round | ✓ | ✓ | Fully synced when live room active |
| Draft board | ✓ | ✓ | Fully synced |
| Settings / roster | ✓ | ✓ | Fully synced |
| **Command Center** | | | |
| Activities | ✓ | ✓ | Fully synced |
| Continue items | ✓ | ✓ | Fully synced |
| Saved questions | ✓ | ✓ | Fully synced |
| Duplicate-send dedupe | Partial | Partial | Baseball refreshes activity (v17); other apps skip within window |
| **Workspace restore** | | | |
| Page restore | ✓ | ✓ | Fully synced |
| Draft restore | ✓ | ✓ | Fully synced |
| Active session restore | ✓ | ✓ | Fully synced |
| AMI warm pool cache | — | — | Local-only (intentional) |
| **Instant Baseball Insight** | | | |
| Latest insight card | ✓ | ✓ | Fully synced (insight store v10) |
| Dismissed insight IDs | ✓ | ✓ | Fully synced |
| Instant solve (pre-cloud) | — | — | Local-only when AMI repo bundled; fallback card always staged (v17) |

---

## v17 pipeline fixes (instant-insight-v17)

| Issue | Root cause | Fix |
|-------|------------|-----|
| Insight card missing after submit | `st.rerun()` aborted script before main-body insight render; no fallback when AMI repo absent on Cloud | Removed rerun; always stage fallback or solver insight; render runs same run after sidebar |
| Command Center empty | Broken `elif blob_updated` resume upsert; duplicate path skipped activity | Fixed resume upsert block; baseball always records activity even on duplicate |
| No diagnostics | Partial submit tracing | `_ami_submit_pipeline` with full step keys in Dev Mode |
| Header missing on draft pages | `render_global_app_chrome` early-return on draft focus pages | Compact banner on all pages |
| Sleepers filters revert | Canonical overwrite on prepare | `mark_sleepers_filter_local_edit`; skip canonical sync when widget matches |

### Submit pipeline diagnostics (Dev Mode → “Baseball Insight submit pipeline”)

`submit_received`, `question_text`, `question_id`, `instant_solve_started`, `instant_solve_finished`, `instant_solve_reason`, `ami_repo_found`, `insight_card_created`, `activity_created`, `continue_item_created`, `command_center_write_status`, `cloud_persist_status`, `duplicate_detected`, `last_exception`

---

## Trend Value / Sleepers / Comparison (AMI context)

| Page | Send hook | Cloud context blob | Instant solve | Priority |
|------|-----------|-------------------|---------------|----------|
| Trend Value | `finalize_trend_context_for_send` | Yes | Needs AMI repo or full-analysis link | High |
| Sleepers | `finalize_sleepers_context_for_send` | Yes | Same | High |
| Comparison | `finalize_comparison_context_for_send` | Yes | Same | High |

**Production note:** Streamlit Cloud baseball deploy must bundle AMI (`AMI_REPO_PATH`) or users get fallback insight + full Applied Intelligence analysis link.

---

## Full sync matrix (v21 audit)

| Feature | Dell → Phone | Phone → Dell | Cloud-backed? | Status | Fix needed |
|---------|--------------|--------------|---------------|--------|------------|
| **Draft settings** | | | | | |
| Draft format (Roto/H2H/etc.) | ✓ | ✓ | Yes — `draft_state.room_format`, workspace envelope | **Synced** | None if workspace save runs |
| Scoring format | ✓ | ✓ | Yes — `room_format` / fantasy filters | **Synced** | Verify live-draft vs simulator keys match |
| Team count | ✓ | ✓ | Yes — `room_team_count` | **Synced** | None |
| Current pick / round | ✓ | ✓ | Yes — canonical board + `draft_board_summary` | **Partial** | Simulator refreshes on send; live draft needs active session |
| Selected team | ✓ | ✓ | Yes — `room_your_team`, `draft_assistant_synced_team` | **Synced** | None |
| **Draft board & queue** | | | | | |
| Draft board picks | ✓ | ✓ | Yes — `draft_room_state` canonical blob | **Synced** | None |
| Draft queue | ✓ | ✓ | Yes — `draft_queue` in workspace | **Synced** | None |
| Watchlist / focus players | ✓ | ✓ | Yes — `draft_assistant_focus_players` | **Synced** | Save after edit |
| Recommendations | — | — | No — recomputed per device | **Local** | Expected; match if board+settings match |
| **Sleepers / tracked** | | | | | |
| Sleepers filters (position, age) | ✓ | ✓ | Yes — `fantasy_sleepers_filters` / `page_filter_state` | **Synced** (v19) | Re-verify after filter edits |
| Sleeper/bust ranked tables | — | — | No — rebuilt from market data | **Local** | AMI cache `_ami_sleepers_snapshot` rebuilt per device |
| **Trades / roster** | | | | | |
| Trades (accepted/rejected) | ✓ | ✓ | Yes — trade analyzer state in workspace | **Partial** | Audit trade blob keys on both devices |
| Roster changes / picks | ✓ | ✓ | Yes — board rows | **Synced** | None |
| Player selections / comparison | ✓ | ✓ | Yes — `comparison_state` | **Synced** | None |
| Player notes | ? | ? | Unknown | **Gap** | Audit if notes persist to cloud |
| **Page state** | | | | | |
| Current page | ✓ | ✓ | Yes — `active_page` in workspace | **Synced** | None |
| Active player / comparison | ✓ | ✓ | Yes — comparison + trend blocks | **Synced** | None |
| Selected filters / tabs | ✓ | ✓ | Yes — `page_filter_state` per page | **Partial** | Local-dirty guard can block restore |
| Trend page settings | ✓ | ✓ | Yes — `trend_state` | **Synced** | None |
| Valuation / historical / career selections | ✓ | ✓ | Yes — workspace envelope filters | **Synced** | Spot-check each page |
| **Insights** | | | | | |
| Latest insight card | ✓ | ✓ | Yes — insight store + activity | **Synced** (v20) | Instant card is same-run local until cloud hydrate |
| Dismissed insights | ✓ | ✓ | Yes — `_ami_dismissed_insight_ids` | **Synced** | None |
| Open Full Analysis links | ✓ | ✓ | Yes — resume key + question_id | **Synced** | None |
| Command Center continue items | ✓ | ✓ | Yes — activity API | **Synced** (v17+) | None |
| **AMI caches (intentional local)** | | | | | |
| `_ami_draft_snapshot` pool | — | — | No | **Local** | Refreshed from board at send |
| `_ami_sleepers_snapshot` | — | — | No | **Local** | Rebuilt when Sleepers page renders |
| Undrafted pool lookup | — | — | No | **Local** | Built from yearly data |

### v21 sync audit next steps

1. Manual pass: change **Roto Draft** on Dell → Phone cold open → confirm format matches.
2. Manual pass: queue reorder on Phone → Dell refresh → confirm order.
3. Manual pass: comparison players on Dell → Phone → same A/B slots.
4. Code pass: trade analyzer + player notes cloud keys (mark **Gap** → **Synced** or document local-only).
5. Continue insight bidirectional tests after each deploy.

---

## v21 baseball-side changes (instant-insight-v21)

| Issue | Fix |
|-------|-----|
| Market Bust Risks reused Nathan Lukes context | `detect_sleepers_send_intent` + bust routing in `finalize_sleepers_context_for_send`; clear stale `sleeper_focus` on section-level bust questions |
| Team 2 positions show `?` in AMI output | Added `filled_roster_display_lines`, `roster_by_position`, `team_roster_with_positions` + diagnostics; **AMI repo** must read these fields if still showing `?` |
| Instant card labels | Question / **Answer** / **Summary** / Status·Confidence / Open Full Analysis / Dismiss |

**Retest after deploy:** Market Bust Risks question, Team 2 roster review (check Dev Mode `roster_display_lines` in diagnostics), Nathan Lukes sleeper (routing only — solver polish is AMI-side).

