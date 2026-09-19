# Recommendation Logic Summary (Live Draft)

Checkpoint: local `dev` stabilization pass (screenshot-driven).
This documents the **current** recommendation engine after the screenshot fixes — review before any future scoring redesign.

## Pipeline (Balanced Recommendation)

1. **Candidate availability** — undrafted players from the live pool (`live_draft_get_available` / scored available frame).
2. **Open required positions (hard filter)** — while starter slots remain open, keep only players who can fill an open need (`filter_candidates_to_team_open_positions` / `_eligible_for_open_need_recommendation`). SS-only is dropped when SS is filled and other starters remain. Multi-pos (SS/2B) may remain if 2B is open. When only UTIL/BN remain, the filter relaxes to BPA.
3. **Multi-position eligibility** — exact slot match first in roster assignment; MI/CI/UTIL flex on a second pass (`assign_roster_to_slot_instances`).
4. **Player Grade** — display of projected fantasy value (`Expected Fantasy Value` / Blended Projection Score scale). Fast Solo may temporarily use a market-proxy grade for sorting only; Model Rank is **not** copied from Market during that window.
5. **Decision Score** — weighted composite from `apply_draft_pick_scoring` / `live_draft_pick_scoring` (production/value + roster fit + scarcity + category need − risk). Exact weights live in that module; Balanced uses the full blend.
6. **Roster Fit / Positional Fit** — how well the player fills current open slots / fit score column.
7. **Positional Scarcity** — replacement-level / quality-supply dropoff (`Scarcity Score`).
8. **Category weaknesses** — canonical `draft_needs.infer_hitter_category_needs` (team sum/mean vs pool median × 0.92 threshold). Live Draft paints the same list as “Categories to strengthen”.
9. **Model Rank** — dense competition rank of **Blended Projection Score** (`method="min"`) once the projection pool is attached. Pending (`—` / “Pending”) until upgrade — never Model:=Market as analytics.
10. **Market Rank** — ADP Rank, FantasyPros Rank fallback.
11. **Fantasy Edge** — `Market Rank − Model Rank` when both ranks are real; pending while Model is pending.
12. **Projected statistics** — format-aware proj_* columns (5×5: HR/RBI/R/SB/AVG).
13. **Trend / sleeper / risk** — risk penalty / projection confidence / survival when present.
14. **Availability / survival urgency** — Survival Probability when available.
15. **Final ranking** — sort primarily by Decision Score (rule-dependent), then value/fit tie-breaks.

### Role of each signal

| Signal | Role |
|--------|------|
| Open-position eligibility | **Hard filter** |
| League-legal positions | **Hard filter** |
| Player Grade / EFV / Blended | **Weighted / primary value** |
| Decision Score | **Final sort key** (Balanced) |
| Roster Fit | **Weighted component** |
| Positional Scarcity | **Weighted component** |
| Category need bonus | **Weighted component** |
| Model / Market / Edge | **Display + value/tie** (Edge also badge evidence) |
| Projected stats | **Display + Why/badge evidence** |
| Survival / risk | **Tie-break / display** |

## Startup strategies (UI terminology)

- **Balanced Recommendation** — full Decision Score blend + open-need filter.
- **Best Market Rank** — prioritize Market Rank (ADP).
- **Best Model Rank** — prioritize Model Rank (Blended rank) when available.
- **Best Projected Fantasy Value / Player Grade** — prioritize EFV / Player Grade.
- **Best Roster Need** — emphasize open-slot / fit scoring.

Auto Pick uses the **same** `score_available_for_rule` path with the room’s configured rule — including open-position filtering.

## Starter vs Bench recommendation behavior

While required starters are open → recommend only players who fill those needs (flex rules apply).  
After starters are satisfied → broaden to Bench/BPA.

## Badge generation

1. Score eligible positive traits (power, speed, AVG, RBI, model bargain, multi-pos, scarce C, best available at open pos, category need).
2. Relevance-rank traits.
3. Emit ~1–3 badges; collapse duplicate concepts.
4. Avoid repeating the same idea; ordinal “Second Best” only as last-resort filler.

## Why Recommended

2–4 player-specific bullets backed by projected stats, open needs, and Model vs Market. Badge claims must be supported (e.g. Speed Boost ↔ projected SB).

## Worked example (illustrative)

Player: OF, proj HR=32, SB=8, Model=18, Market=29, open needs=[OF, SB weak]

- Hard filter: OF open → kept  
- Edge = 29 − 18 = +11 → Model Bargain eligible  
- Badge set e.g. `Elite Power`, `Model Bargain`, `Fills OF Slot`  
- Why: “Projects 32 HR — elite power production”; “Model ranks him #18 vs market #29 — clear bargain”; “Fills your open OF starter need”  
- Decision Score: high production + fit + edge components → near top of Balanced list

## Draft Lab roster Have/Gap

Uses the same slot-assignment algorithm as Live Draft: exact starters → flex → Bench. Surplus 1B fill Bench rather than inflating 1B Have.

## Queue

Canonical ordered list in `draft_queue` / `DRAFT_QUEUE_KEY`. Sidebar and main chips both read that list; Sortable commits via `reorder_user_draft_queue` or remounts on reject so order cannot diverge.
