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
| Latest insight (`_ami_pending_insight`) | Cloud | Insight store v10 + URL deep link |
| Dismissed insight IDs | Cloud | `_ami_dismissed_insight_ids` |
| Continue / full-analysis links | Cloud | Resume key + question_id in activity |
| Instant solve result | **Local** | Staged immediately; cloud via activity + blob on send |

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

## Instant Baseball Insight E2E verification (v17 target)

| # | Check | v16 | v17 target |
|---|-------|-----|------------|
| 1 | Insight card appears immediately on submit | Fail (no AMI + rerun) | Pass (fallback card, no rerun) |
| 2 | Command Center activity created | Fail (resume elif bug) | Pass |
| 3 | Continue item created | Fail | Pass (flush + fixed upsert) |
| 4 | Open Full Analysis works | — | Pass |
| 5 | Phone ↔ Dell same insight | Partial | Re-verify after v17 |
