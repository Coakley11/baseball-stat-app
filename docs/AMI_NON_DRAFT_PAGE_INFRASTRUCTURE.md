# AMI Infrastructure Plan — Non-Draft Baseball Pages

Reusable pattern from Draft AMI: **context package → hydration → routing → solver mode → instant insight**.

---

## Shared pipeline (all pages)

| Stage | Baseball | AMI |
|-------|----------|-----|
| Page cache | `cache_*_ami_context(session, page=...)` | — |
| Send merge | `finalize_*_context_for_send(ctx, session)` | — |
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

## Implementation order (after Draft AMI stable)

1. Sleepers — cache already exists; polish routing + instant insight
2. Trends — `trend_summary` already routed; add page cache at send
3. Historical — wire `historical_snapshot` send promotion
4. Start/Sit — new lineup snapshot from Lineup Assistant
5. Trades — new trade builder integration

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
