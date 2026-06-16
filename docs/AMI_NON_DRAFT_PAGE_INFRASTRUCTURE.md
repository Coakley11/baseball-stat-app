# AMI Infrastructure Plan — Non-Draft Baseball Pages

Reusable pattern from Draft AMI: **context package → hydration → routing → solver mode → instant insight**.

---

## Current status (2026-06-16)

Send-side promotion is dispatched by `promote_page_ami_context_at_send` in `baseball_ami_pages.py`.

| Page | Send hook | Routing detector | Diagnostics | Send-side status |
|------|-----------|------------------|-------------|------------------|
| Comparison | `finalize_comparison_context_for_send` | `detect_comparison_send_intent` | `build_comparison_send_diagnostics` | **Done** — player parser hardened 2026-06-16 (strips trailing question fragments); regression tests in `tests/test_comparison_ami_send.py` |
| Trend Value | `finalize_trend_context_for_send` | (trend modes) | `build_trend_send_diagnostics` | **Done** — promotes `trend_summary`/`player`/`metrics`/`trend_snapshot`/`trend_window`; clears `player_a/b` to avoid compare-mode leak |
| Sleepers / Busts | `finalize_sleepers_context_for_send` | `detect_sleepers_send_intent` | `build_sleepers_send_diagnostics` | **Done (send)** — bust vs sleeper routing + stale-context clearing; quality polish is AMI-side (see backlog B2) |
| Valuation | `finalize_valuation_context_for_send` | `valuation_analysis` | `build_valuation_send_diagnostics` | **Done 2026-06-16** — promotes `valuation_snapshot`, selected player, draft status, top players; tested in `tests/test_valhist_career_ami_send.py` |
| Historical Explorer | `finalize_historical_context_for_send` | `historical_analysis` | `build_historical_send_diagnostics` | **Done 2026-06-16** — promotes `historical_snapshot`, year range, sort stat, top players; tested |
| Career Explorer | `finalize_career_context_for_send` | `career_analysis` | `build_career_send_diagnostics` | **Done 2026-06-16** — promotes filters, year range, sort stat, team, snapshot; tested |

**Priority order (after sync audit):** 1) Comparison · 2) Trend Value · 3) Sleepers/Busts quality
· 4) Valuation / Historical / Career send hooks. Open AMI quality issues: `docs/AMI_BACKLOG.md`.

---

## Shared pipeline (all pages)

| Stage | Baseball | AMI |
|-------|----------|-----|
| Page cache | `cache_*_ami_context(session, page=...)` | — |
| Send merge | `promote_page_ami_context_at_send` in `baseball_ami_pages.py` | — |
| Draft send merge | `finalize_draft_context_for_send` → `attach_draft_team_to_context` | — |
| Position/index maps | `build_player_position_index_from_session` | `_attach_player_position_index` |
| Routing | — | `route_suite_question` → `problem_type_id` |
| Solve | `solve_instant_baseball_insight` | `dispatch_solver` |
| Display | `stage_pending_insight` + insight card | Full analysis UI |

---

## 1. Trends Explorer

**Example questions:** What trend stands out? Is this sustainable? Buy low or sell high?

| Item | Plan |
|------|------|
| Context package | `trend_summary`, `player`, `stat_focus`, `slope`, `r2`, `season_window` |
| Required data | Selected player trend series, league context |
| Hydration | Blob `context.trend_summary` + `player` |
| Routing | `BASEBALL_TREND` / intent `INTENT_IS_MEANINGFUL` |
| Cache key | `_ami_trend_snapshot` |

---

## 2. Sleepers Page

**Example questions:** Best sleeper? Highest upside? Biggest breakout candidate?

| Item | Plan |
|------|------|
| Context package | `sleepers_snapshot`, `sleeper_candidates`, `drafted_exclusions`, `roster_needs` |
| Required data | Filtered sleeper list with Fantasy Edge, exclusions |
| Hydration | Existing `sleepers_snapshot` path (partially wired) |
| Routing | `player_why` / `sleeper` / `sleeper_risk` modes |
| Cache key | `_ami_sleepers_snapshot` (exists) |

---

## 3. Trades

**Example questions:** Should I accept this trade? Who wins the trade? Fair value?

| Item | Plan |
|------|------|
| Context package | `player_a`, `player_b`, `trade_side_a`, `trade_side_b`, `category_impact` |
| Required data | Trade builder state, projected category deltas |
| Hydration | New `trade_snapshot` blob section |
| Routing | `BASEBALL_PLAYER_COMPARE` + trade-specific mode `trade_fairness` |
| Cache key | `_ami_trade_snapshot` |

---

## 4. Start/Sit

**Example questions:** Start Player A or Player B? Which lineup is better?

| Item | Plan |
|------|------|
| Context package | `lineup_a`, `lineup_b`, `matchup_week`, `expected_value_by_slot` |
| Required data | Lineup assistant state, weekly projections |
| Hydration | `lineup_snapshot` from Fantasy Lineup Assistant |
| Routing | `INTENT_WHO_IS_BETTER` + `start_sit` mode |
| Cache key | `_ami_lineup_snapshot` |

---

## 5. Historical Explorer

**Example questions:** Similar historical players? Comparable seasons?

| Item | Plan |
|------|------|
| Context package | `historical_snapshot`, `top_rows`, `player`, `comp_season` |
| Required data | Historical comp table, selected player season line |
| Hydration | Existing `historical_snapshot` (partial) |
| Routing | `BASEBALL_HISTORICAL` |
| Cache key | `_ami_historical_snapshot` |

---

## 3. Comparison Tool

**Example questions:** Who is the better draft pick? Better long-term value? Better rest-of-season outlook?

| Item | Status |
|------|--------|
| Context package | `player_a`, `player_b`, `comparison_chart`, `comparison_differences`, `metrics` |
| Required data | Sig Player A/B, compare stat, advanced trend intel rows |
| Hydration | `comparison_state` + `_ami_comparison_context` |
| Routing | `detect_comparison_send_intent` → `comparison_draft_pick`, `comparison_head_to_head`, `comparison_long_term`, `comparison_ros` |
| Cache key | `_ami_comparison_context` (page render) |
| Send hook | `finalize_comparison_context_for_send` + `build_comparison_send_diagnostics` |
| Diagnostics | `comparison_send_diagnostics` merged into `send_pipeline_diagnostics` |

---

## Question routing categories (draft-complete reference)

| Category | Detector | Solver mode |
|----------|----------|-------------|
| Player why | `is_player_explanation_question` | `player_why` |
| Position BPA | `is_position_best_available_question` | `position_best_available` |
| Timing | `is_draft_timing_question` | `draft_timing_decision` |
| Review | `is_draft_review_question` | `draft_review` |
| Roster needs | `is_roster_needs_question` | `roster_needs` |
| Compare | `is_draft_head_to_head_question` | `draft_player_compare` |
| Market | `is_draft_market_prediction_question` | `draft_market_prediction` |

Non-draft pages should add parallel detectors in `applied_math_problem_router._route_baseball` before generic fallbacks.
