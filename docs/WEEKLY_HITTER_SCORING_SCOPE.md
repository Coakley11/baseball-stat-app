# Weekly Hitter Fantasy Scoring — Revised Scope (Phase 1)

**Last updated:** 2026-07-11  
**Status:** Scoped — not yet implemented  
**Repo:** `baseball-stat-app` (`dev`)

---

## Executive summary

This phase builds a **hitter-only** weekly fantasy scoring system driven entirely by the league’s **configured scoring categories**. It extends the existing Fantasy Lineup Assistant lock/save flow with baselines, live weekly stats, commissioner finalization, and Fantasy Standings integration.

**Explicitly out of scope:** all pitcher statistics, pitcher baselines, pitcher UI, pitching formulas, and future pitcher architecture.

---

## What already exists (build on, do not rewrite)

| Area | Location | Current behavior | Gap vs spec |
|------|----------|------------------|-------------|
| Weekly lineup draft/lock | `fantasy_weekly_lineup.py`, `fantasy_weekly_lineup_ui.py` | Draft auto-save; **Save Lineup** locks week; circular board | No baseline ledger; no live weekly display |
| Lock snapshot | `save_weekly_lineup()` → `stats_snapshot` | Hardcoded `ROTO_STARTER_CATEGORIES` season totals at lock time | Not a baseline; not category-driven; not delta-based |
| Hitter-only slots | `fantasy_weekly_lineup.py` | Skips P/SP/RP; UTIL rejects pitchers | ✅ Keep |
| Stat source | Standings Tracker → `fantasy_current_roster_stats` | MLB API / CSV: R, HR, RBI, SB, H, AB, BB, BA, OBP, SLG, OPS | Reuse for current totals |
| Global format | `global_fantasy_settings_state.py` | `5x5 Roto` / `Points League` via `room_format` | Not per-league category picker |
| Points weights (UI only) | `build_lineup_assistant_scores()` in `streamlit_app.py` | Default weights: R=1, RBI=1, HR=4, SB=2, H=1, BB=1, OPS=10 | Not persisted as league scoring config; not used in weekly scoring |
| Waiver categories | `fantasy_waiver_wire.py` → `waiver_categories_for_context()` | 5×5: HR/RBI/R/SB/AVG; Points adds OPS | Closest existing category resolver — **reuse pattern** |
| Season standings | `score_fantasy_rosters_from_stats()` | Full-roster season roto/points | Does not consume weekly locked starters |
| Pitcher isolation | `HITTER_ONLY_FORMATS`, `fantasy_format_includes_pitching()` | Pitching gated off for hitter-only formats | ✅ No pitcher work in this phase |

---

## Category-driven design (source of truth)

### Resolver: `resolve_hitter_scoring_profile(context) → HitterScoringProfile`

New module: **`fantasy_weekly_hitter_scoring.py`** (name TBD).

Reads from active league context (priority order):

1. `context.scoring_settings.hitter_categories` (new, commissioner-authored when needed)
2. `context.scoring_settings.points_weights` (new, for points leagues)
3. `context.fantasy_format` + `room_format` fallback via `waiver_categories_for_context()` pattern
4. If points league and weights incomplete → **block scoring** and prompt commissioner setup (no invented defaults)

### Supported configured categories (Phase 1)

| Category | Roto display | Points display | Hidden calc only |
|----------|--------------|----------------|------------------|
| R | ✅ | ✅ (if weighted) | — |
| HR | ✅ | ✅ | — |
| RBI | ✅ | ✅ | — |
| SB | ✅ | ✅ | — |
| AVG | ✅ | — | Requires H, AB |
| H | If configured | If weighted | Supports AVG |
| OBP | If configured | — | Requires H, AB, BB, HBP, SF |
| OPS | If configured | If weighted | Requires OBP + SLG components |
| BB | **Only if configured** | **Only if point value set** | Hidden for OBP when OBP enabled |

### Standard 5×5 roto (default when format = `5x5 Roto`)

**R, HR, RBI, SB, AVG** — walks are **not** scored or displayed.

### Walks rule

- Do **not** add BB as a default category.
- BB appears in UI/standings **only** when explicitly configured.
- When OBP is configured, store BB (and HBP, SF if available) as **hidden calculation fields** only.

### Rate stat rules

- **Never** subtract one rate from another.
- **AVG:** weekly = weekly H / weekly AB; team = sum(starter H) / sum(starter AB).
- **OBP:** only when configured; unavailable if required components missing from data source.
- **OPS:** only when configured; from valid weekly OBP + weekly SLG; use minimum hidden inputs (H, AB, BB, HBP, SF, TB or 1B/2B/3B/HR).

### Points leagues

- Read saved `points_weights` per event.
- Baseline, delta, multiply, sum **only locked starters**.
- BB counts only when `points_weights["BB"]` is set.

---

## No pitcher support (Phase 1)

Do **not** add or extend:

- Pitcher roster handling, baselines, ledgers, UI
- W, L, SV, HLD, K, IP, ERA, WHIP, ER
- Pitcher standings integration
- Generic schema “ready for pitching later”

Existing pitcher code in waiver/standings remains behind `fantasy_format_includes_pitching()` and is **untouched**.

---

## Storage schema (minimal hitter ledger)

Stored under league context `workflow`:

```text
workflow.weekly_hitter_scoring/
  weeks/
    {canonical_league_id}|{team_key}|week_{n}/
      status: draft | locked | finalized
      locked_at, finalized_at
      assignments: {slot_key: player_key}
      bench: [player_key, ...]
      player_snapshot: {player_key: {name, player_id, slot, is_starter}}
      baseline: {player_key: {configured cats + hidden fields}}
      baseline_created_at  # immutable after first lock
      live_cache: {player_key: {current totals}}  # refreshable, not baseline
      weekly_results: {player_key: {configured display cats}}
      team_totals: {configured cats + points_total?}
      finalized_result_id: {league_id}|week_{n}  # idempotency key
```

**Stable keys:** canonical league ID (`resolve_canonical_league_id`), team identity (`owned_team_for_user` / `my_team_name`), week number, `normalize_player_key` / `player_id`.

**Idempotency:**

- Baseline created **once** on first successful Save Lineup; repeated Save is no-op for baseline.
- Finalize uses `{league_id}|week_{n}` to prevent duplicate standings writes.

---

## Feature flow (10-step implementation order)

### Step 1 — Inspect and document existing hitter scoring configuration ✅ (this doc)

### Step 2 — Define supported configured hitter categories

- Implement `HitterScoringProfile` dataclass
- Map format → display categories + hidden fields + points weights
- Unit tests: 5×5 excludes BB; BB when configured; OBP hidden components

### Step 3 — Minimal weekly hitter baseline and ledger

- On **Save Lineup**: lock assignments, capture per-player cumulative baseline for configured + hidden fields
- Preserve starter/bench designation snapshot
- Idempotent baseline creation

### Step 4 — Calculate configured weekly hitter statistics

- `weekly_value = current_cumulative - baseline` for counting cats
- Rate cats per spec (AVG, OBP, OPS)
- Only locked starters count toward team totals
- Bench stats computed for display but flagged `counts_toward_score: false`

### Step 5 — Locked weekly dashboard

- After lock: board visible, circles filled, drag disabled, Reset hidden
- Show `Lineup locked for Week N`
- Live weekly stats per starter (configured categories only)
- Bench visible with “Bench statistics do not count”

### Step 6 — Compact player detail

- Tap/click face → modal/expand: name, photo, slot, weekly cats, season totals, baseline, last update, prior weeks
- No unrelated stat table; no pitcher section

### Step 7 — Team weekly totals

- Roto: sum counting; combine H/AB for AVG; combine OBP/OPS components at team level
- Points: apply league weights to starter deltas only

### Step 8 — Commissioner Finalize Week

- `Finalize Week N` (commissioner only, `is_lineup_format_commissioner` pattern)
- Pre-flight: refresh stats, preview teams, flag unlocked lineups, missing data, confirm
- Freeze player + team results; idempotent finalize record

### Step 9 — Fantasy Standings integration

- Write **only configured categories** to standings cumulative store
- Counting: add finalized weekly totals
- AVG/OBP/OPS: preserve underlying components; recalculate cumulative rates (never average weekly rates)
- Points: add weekly team point total + preserve weekly history entry

### Step 10 — Next week

- After finalize: week N locked forever; week N+1 editable
- All rostered hitters on Bench; empty circles
- Message: “Week N is complete… Set your Week N+1 lineup.”
- No auto-carry of starters

---

## Midweek roster changes

Locked week uses **frozen player snapshot** from lock time.

- Traded/dropped player still counts for team that started him that week.
- Current roster changes affect only future unlocked weeks.
- Do not rewrite locked-week assignments from live roster.

---

## Files expected to change (implementation)

| File | Role |
|------|------|
| `fantasy_weekly_hitter_scoring.py` | **New** — profile resolver, baseline, deltas, team totals, finalize |
| `fantasy_weekly_lineup.py` | Wire lock → baseline; deprecate hardcoded `stats_snapshot` shape |
| `fantasy_weekly_lineup_ui.py` | Locked dashboard, live stats, player detail, finalize button |
| `fantasy_lineup_interactive_board.py` | Read-only locked mode (partially exists) |
| `fantasy_league_context.py` | Optional `scoring_settings` extension for points weights |
| `streamlit_app.py` | Standings write path for finalized weeks |
| `fantasy_in_season_state.py` | Optional cache for live stat refresh |
| `tests/test_fantasy_weekly_hitter_scoring.py` | **New** — 20 tests from spec |

**Not changing:** pitcher modules, draft scoring pool, live draft pick scoring.

---

## Test plan (20 required cases)

1. Only configured categories captured in baseline  
2. Unconfigured categories not shown or scored  
3. BB excluded from standard 5×5 roto  
4. BB works when explicitly configured as roto cat  
5. BB as points event only when point value configured  
6. Hidden BB/HBP/SF for OBP without displaying BB  
7. No pitcher data or UI created  
8. Save creates exactly one baseline  
9. Refresh/rerun does not replace baseline  
10. Counting-stat deltas correct  
11. Weekly AVG = weekly H / weekly AB  
12. Team AVG = combined starter H / AB  
13. OBP/OPS use valid underlying components; unavailable when data missing  
14. Bench statistics do not count toward team score  
15. Only locked starters count  
16. Points use league-configured weights  
17. Finalize commissioner-only and idempotent  
18. Standings insertion cannot duplicate  
19. Next week: empty circles, all players on Bench  
20. Prior weeks unchanged after trades/drops  

---

## Performance guardrails

- Cache `HitterScoringProfile` per league context per page run (same pattern as `fantasy_lineup_perf.py`)
- Refresh live stats without rewriting baseline
- Finalize batch: one standings write per team per week
- Dev-only timing via `page_perf_phases` (`weekly_hitter_baseline`, `weekly_hitter_deltas`, `weekly_finalize`)

---

## Completion report checklist (post-implementation)

- [ ] Exact hitter categories supported (list)
- [ ] Roto vs points vs hidden fields documented
- [ ] Confirmation: no pitcher system added
- [ ] Storage schema finalized
- [ ] Files changed
- [ ] Tests run (20/20)
- [ ] Performance results (cold/warm)
- [ ] Feature commit + deploy marker
- [ ] Live verification checklist

---

## Central rule

> Store and display only the fantasy categories configured for the league. Count only locked starters. Do not build pitcher scoring in this phase.
