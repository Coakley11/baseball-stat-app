# Phone ↔ Dell Sync Audit

**Goal:** One authoritative cloud-backed state so a change on Dell appears on Phone (and vice versa) without silent local-only drift.

**Last updated:** 2026-06-16 — full matrix re-verified against code (v21+ expansion 2026-05-27)

**Verification (2026-06-16):** Every cited sync function (`sync_workspace_protocol`,
`prepare_baseball_workspace`, `autosave_baseball_state`, `force_save_baseball_state`,
`render_cross_device_sync_debug`, `claim_user_page_ownership`,
`should_skip_workspace_restore_for_resume`, `persist_insight_dismissal_to_cloud`,
`apply_cloud_historical_state_if_allowed`, `apply_comparison_source_state_from_ami`,
`apply_market_bust_context_at_send`), every per-page state module
(`draft_room_state`, `comparison_state`, `trend_state`, `fantasy_state`, `valuation_state`,
`historical_state`, `career_totals_state`), every force-save reason
(`draft_room_pick`, `draft_edit`, `comparison_edit`, `trend_edit`, `fantasy_edit`,
`valuation_edit`, `historical_edit`, `career_edit`, `insight_persist`, `applied_math_send` —
all whitelisted in `suite_user_persistence.py`), and the `trend_chart_player` envelope key
were confirmed present and wired. No matrix corrections required.

**How sync works:** Supabase `full_session` blob (`suite_cloud_state.FULL_SESSION_KEY`) + local disk `data/baseball_user_state.json`. Startup: `prepare_baseball_workspace()` → `sync_workspace_protocol(cloud_first=True)`. Save: `autosave_baseball_state()` / `force_save_baseball_state(reason=...)`.

**Debug:** `?dev=1` → sidebar “Workspace sync trace” (`render_cross_device_sync_debug()`).

---

## Status legend

| Status | Meaning |
|--------|---------|
| **Synced** | Cloud-backed; bidirectional after save + refresh |
| **Partial** | Cloud exists but gaps, race conditions, or envelope/debug mismatch |
| **Local** | Intentionally device-only (recomputed tables, AMI caches, widget state) |
| **Broken** | Known cross-device failure |
| **Gap** | Not persisted to cloud today |

---

## Master sync matrix

### 1. Draft Room Simulator

| Feature | Dell → Phone | Phone → Dell | Cloud-backed? | Status | Recommended fix |
|---------|--------------|--------------|---------------|--------|-----------------|
| Draft picks (board rows) | ✓ | ✓ | Yes — `draft_room_state`, `draft_room_table`, `page_filter_state` | **Synced** | `force_save(reason="draft_room_pick")` after picks |
| Current round / pick | ✓ | ✓ | Yes — derived from board `Pick`/`Round` columns | **Synced** | None; authoritative via canonical board |
| Draft board state (full table) | ✓ | ✓ | Yes — `draft_room_state` blob | **Synced** | None |
| Draft queue | ✓ | ✓ | Yes — `draft_state.queue`, `draft_workflow.queue` | **Synced** | Save after queue edit |
| Watchlist / focus players | ✓ | ✓ | Yes — `draft_assistant_focus_players`, `draft_workflow.watchlist_*` | **Synced** | Save after watchlist edit |
| Team selections (`room_your_team`) | ✓ | ✓ | Yes — global + `draft_state` | **Synced** | None |
| Draft settings (format, teams, rounds) | ✓ | ✓ | Yes — `room_format`, `room_team_count`, `room_rounds`, page block | **Partial** | Envelope omits `room_window`/`room_team_names`; full blob is authoritative |
| Player pool / rankings | — | — | No | **Local** | Expected — rebuilt from yearly/market data |
| Board editor widget cache | — | — | No | **Local** | Expected Streamlit widget state |
| AMI draft cache (`_ami_draft_snapshot`) | — | — | No | **Local** | Rebuilt at send from canonical board |

### 2. Draft Assistant

| Feature | Dell → Phone | Phone → Dell | Cloud-backed? | Status | Recommended fix |
|---------|--------------|--------------|---------------|--------|-----------------|
| Recommendations table | — | — | No | **Local** | Expected if board + settings match |
| Saved AMI context (post-send) | ✓ | ✓ | Yes — activity API + context blob | **Synced** | Ensure `AMI_REPO_PATH` on cloud deploy |
| Questions / insights | ✓ | ✓ | Yes — `_INSIGHT_KEYS` + activity | **Synced** (v20) | Instant card same-run local until cloud hydrate |
| Workspace / page settings | ✓ | ✓ | Yes — `page_filter_state["Draft Assistant Simulator"]` | **Synced** | `force_save(reason="draft_edit")` |
| Board-linked pick/round | ✓ | ✓ | Yes — via `draft_room_state` | **Synced** | Same as Draft Room |
| Queue / watchlist (shared) | ✓ | ✓ | Yes — `draft_state` | **Synced** | Same as Draft Room |

### 3. Comparison Tool

| Feature | Dell → Phone | Phone → Dell | Cloud-backed? | Status | Recommended fix |
|---------|--------------|--------------|---------------|--------|-----------------|
| Selected Player A | ✓ | ✓ | Yes — `comparison_state.player_a`, `sig_player_a_clean` | **Synced** | `force_save(reason="comparison_edit")` |
| Selected Player B | ✓ | ✓ | Yes — `comparison_state.player_b`, `sig_player_b_clean` | **Synced** | Same |
| Comparison settings (stat, axis, year range) | ✓ | ✓ | Yes — `comparison_state.chart`, page block | **Synced** | `comparison_state_dirty` blocks overwrite while editing |
| Generated insights | ✓ | ✓ | Yes — `_ami_pending_insight` + activity | **Synced** | AMI return via `apply_comparison_source_state_from_ami` |
| AMI comparison cache (`_ami_comparison_context`) | — | — | No | **Local** | Rebuilt when comparison chart renders; promoted at send |

### 4. Trends Page (Trend Value)

| Feature | Dell → Phone | Phone → Dell | Cloud-backed? | Status | Recommended fix |
|---------|--------------|--------------|---------------|--------|-----------------|
| Selected player (chart) | ✓ | ✓ | Yes — `trend_state.chart_player`, `single_trend_dashboard_player` | **Synced** | Envelope now includes `trend_chart_player` (v21+) |
| Selected metrics | ✓ | ✓ | Yes — `trend_state.chart`, page block | **Synced** | `force_save(reason="trend_edit")` |
| Trend filters (lag, min G, position) | ✓ | ✓ | Yes — `trend_state.filters` | **Synced** | None |
| Multi-player list | ✓ | ✓ | Yes — `trend_state.players_multi` | **Synced** | Envelope uses canonical meta fallback (v21+) |
| Generated insights | ✓ | ✓ | Yes — activity + `_INSIGHT_KEYS` | **Synced** | `finalize_trend_context_for_send` |

### 5. Sleepers / Busts

| Feature | Dell → Phone | Phone → Dell | Cloud-backed? | Status | Recommended fix |
|---------|--------------|--------------|---------------|--------|-----------------|
| Position filter | ✓ | ✓ | Yes — `fantasy_state.sleepers.filters`, `page_filter_state` | **Synced** (v19) | Re-verify after multiselect edits |
| Age filter | ✓ | ✓ | Yes — same | **Synced** (v19) | `mark_fantasy_local_edit` + save |
| Sleeper selections (selected player) | ✓ | ✓ | Yes — `fantasy_market_selected_player` | **Synced** | None |
| Bust selections | ✓ | ✓ | Yes — same canonical fantasy state | **Synced** | None |
| Ranked sleeper/bust tables | — | — | No | **Local** | Rebuilt from market data per device |
| Generated insights | ✓ | ✓ | Yes — activity + blob | **Synced** | Bust routing via `apply_market_bust_context_at_send` (v21+) |

### 6. Valuation Page

| Feature | Dell → Phone | Phone → Dell | Cloud-backed? | Status | Recommended fix |
|---------|--------------|--------------|---------------|--------|-----------------|
| Filters (lag, position, thresholds) | ✓ | ✓ | Yes — `valuation_state.filters`, `page_filter_state` | **Synced** | `force_save(reason="valuation_edit")` |
| Selected player | ✓ | ✓ | Yes — `valuation_state.selected_player` | **Synced** | None |
| Rankings table | — | — | No | **Local** | Expected — recomputed from filters |
| Generated insights | ✓ | ✓ | Yes — activity + `_INSIGHT_KEYS` | **Synced** | None |

### 7. Historical Explorer

| Feature | Dell → Phone | Phone → Dell | Cloud-backed? | Status | Recommended fix |
|---------|--------------|--------------|---------------|--------|-----------------|
| Selected player | — | — | N/A | **N/A** | Filters-only page (no single canonical player) |
| Selected era / year range | ✓ | ✓ | Yes — `historical_state.filters` | **Synced** | `force_save(reason="historical_edit")` |
| Filters (sort, hand, position, team) | ✓ | ✓ | Yes — same | **Synced** | `apply_cloud_historical_state_if_allowed` |
| Generated insights | ✓ | ✓ | Yes — activity + blob | **Synced** | None |

### 8. Career Explorer (Career Totals)

| Feature | Dell → Phone | Phone → Dell | Cloud-backed? | Status | Recommended fix |
|---------|--------------|--------------|---------------|--------|-----------------|
| Selected player | — | — | N/A | **N/A** | Filters-only page |
| Filters (year range, sort, team, mins) | ✓ | ✓ | Yes — `career_state.filters` | **Synced** | `force_save(reason="career_edit")` |
| Generated insights | ✓ | ✓ | Yes — activity + blob | **Synced** | None |

### 9. Workspace Restore

| Feature | Dell → Phone | Phone → Dell | Cloud-backed? | Status | Recommended fix |
|---------|--------------|--------------|---------------|--------|-----------------|
| Last page opened | ✓ | ✓ | Yes — `active_page` | **Partial** | `claim_user_page_ownership` can block stale cloud page |
| Last selected player | ✓ | ✓ | Yes — per-page canonical state | **Synced** | Via comparison/trend/valuation blocks |
| Last generated insight | ✓ | ✓ | Yes — `_ami_pending_insight`, activity | **Partial** | Skip overwrite when `_ami_insight_return_preserve` |
| Navigation state | ✓ | ✓ | Yes — `page_filter_state`, workspace envelope | **Synced** | Full blob authoritative over envelope |
| Dismissed insights | ✓ | ✓ | Yes — `_ami_dismissed_insight_ids` | **Synced** | `persist_insight_dismissal_to_cloud` |
| Continue items | ✓ | ✓ | Yes — activity API resume keys | **Synced** | None |
| AMI resume URL params | Blocks restore | Blocks restore | No | **By design** | `should_skip_workspace_restore_for_resume` |

---

## Cross-cutting behaviors

| Behavior | Impact |
|----------|--------|
| Cloud-first on tie | Dell cold-open prefers cloud (`pick_restore_session`) |
| Disk wins more draft picks | `draft_room_disk_beats_stale_cloud` protects in-progress boards |
| Local-dirty guards | `comparison_state_dirty`, `draft_room_state_dirty`, `fantasy_state` dirty flags block cloud overwrite during edits |
| Post-restore autosave block | One-rerun cooldown after restore prevents wipe |
| Force-save reasons | `comparison_edit`, `trend_edit`, `draft_room_pick`, `fantasy_edit`, `insight_persist`, `applied_math_send` |

---

## Manual verification checklist

1. **Draft format:** Dell → Roto Draft → save → Phone cold open → same format.
2. **Queue:** Phone reorder → save → Dell refresh → same order.
3. **Comparison:** Dell set Player A/B → Phone → same slots.
4. **Trend:** Phone change metric → Dell → same chart settings.
5. **Sleepers filters:** Dell position filter → Phone → same filter.
6. **Insight:** Dell create insight → Phone refresh → same card; reverse direction.
7. **Dismiss:** Phone dismiss → Dell → dismissed.

---

## Known gaps (priority order)

| P | Gap | Fix |
|---|-----|-----|
| P1 | Trade analyzer state sync unverified | Audit trade blob keys; add manual test |
| P1 | Player notes cloud persistence unknown | Audit or document local-only |
| P2 | Recommendations / ranked tables local-only | Document as intentional |
| P2 | Instant insight same-run local until cloud save | Run cross-device test after `insight_persist` force-save |
| P3 | Envelope `draft_state` omits some room keys | Rely on full `draft_room_state` blob (already synced) |

---

## AMI infrastructure status (non-draft)

| Page | Send hook | Routing hints | Diagnostics | Priority |
|------|-----------|---------------|-------------|----------|
| Comparison | `finalize_comparison_context_for_send` | `comparison_draft_pick`, `comparison_head_to_head`, etc. | `comparison_send_diagnostics` | **Active** (v21+) |
| Trend Value | `finalize_trend_context_for_send` | trend modes | `trend_send_diagnostics` | High |
| Sleepers/Busts | `finalize_sleepers_context_for_send` + global bust | `sleeper_take`, `bust_risk_review` | `sleepers_send_diagnostics` | High |
| Valuation | partial via `build_baseball_applied_math_context` | — | — | Medium |
| Historical / Career | partial snapshots | — | — | Medium |

**Open AMI quality backlog (deferred behind this sync audit):** see `docs/AMI_BACKLOG.md`
(Nathan Lukes parser, Market Bust Risks routing, Team 2 roster-needs, Team 2 weakest-pick).

**Next infrastructure priorities (after sync audit closes):** 1) Comparison AMI, 2) Trend Value
AMI, 3) Sleepers/Busts AMI quality, 4) Valuation / Historical / Career AMI infrastructure.

---

## Deploy history (instant insight)

| Build | Highlights |
|-------|------------|
| v17 | Submit pipeline, Command Center activity, no rerun |
| v19 | Team positions, sleepers filter persistence |
| v20 | SessionState staging, inline insight card |
| v21 | Bust routing, roster position payload, card polish, sync audit matrix |

---

## Authoritative sources

| Field | Source |
|-------|--------|
| `current_pick` / `draft_round` | `draft_board_summary_for_team` or live `slot` |
| Roster positions | `user_roster_detail`, `roster_position_index`, yearly pool at send |
| Comparison players | `comparison_state.players` canonical |
| Trend player | `trend_state.chart_player` |
| Sleepers filters | `fantasy_state.sleepers.filters` |
| Insights | Activity API + `_ami_pending_insight` in full blob |
