# Baseball AMI Acceptance Report

**Date:** 2026-06-13  
**Build:** `2026-06-13-baseball-ami-analyst-frame-v17`  
**Harness:** `ami_acceptance_harness.py`  
**Automated result:** **8/8 PASS** (`tests/test_ami_acceptance.py`)

## Methodology

This is **not** a live Command Center LLM run. The harness:

1. Builds a **realistic 12-team draft scenario** (5 picks made, user roster of 2, C/SS needs, queue/watchlist/tracked players, scarcity, recommendations).
2. Calls the same **`cache_*_ami_context` + `build_baseball_applied_math_context`** path used at AMI send time.
3. **Audits** every `PAGE_CONTEXT_REQUIREMENTS` field for the active page.
4. Runs a **rule-based analyst stub** (`simulate_analyst_response`) that proves the structured context supports the six-level answer template (direct → why → scarcity → risk → alternatives → what-if).

**Limitation:** Actual Applied Intelligence solver responses were not invoked (no API in CI). Context completeness + stub quality gate the pipeline before manual Command Center testing.

## Test scenario

| Field | Value |
|-------|--------|
| User team | Daniel |
| Roster | Juan Soto, Elly De La Cruz |
| Drafted (league) | Aaron Judge, Juan Soto, Corbin Carroll, Mookie Betts, Elly De La Cruz |
| Current pick | 6 |
| Queue | Cal Raleigh, Bobby Witt Jr., Junior Caminero |
| Watchlist | Cal Raleigh, Bobby Witt Jr. |
| Tracked | Vladimir Guerrero Jr., Yordan Alvarez |
| Position needs | C, SS |
| Category needs | HR, SB |
| Scarcity index | 2.4 |
| Top recommendation | Cal Raleigh (C) |
| Available pool | Cal Raleigh, Bobby Witt Jr., Junior Caminero, Vladimir Guerrero Jr. |

Live Draft scenario reuses the canonical board from above plus in-progress live room (pick 5, round 2, my next pick 8).

## Results by acceptance test

### Test 1 — Draft board awareness

**Question:** Who should I draft next?

| Page | Result | Stub excerpt |
|------|--------|--------------|
| Draft Assistant | **PASS** | Draft **Cal Raleigh** — roster needs C/SS; scarcity 2.4; alternatives Junior Caminero, Vlad Jr. |
| Live Draft Room | **PASS** | Draft **Cal Raleigh** — on-clock context; 5 drafted players in canonical board |

**Verified:** Drafted set (5 players), available pool (4), recommendation not from drafted list.

### Test 2 — Roster awareness

**Question:** What does my roster need?

| Result | **PASS** |
|--------|----------|
| Stub | 2 players on roster; position gaps C, SS; category needs HR, SB |

### Test 3 — Scarcity awareness

**Question:** Should I take a catcher now or wait?

| Result | **PASS** |
|--------|----------|
| Stub | Catcher tier thinning; scarcity index 2.4; 4 available names; take-now vs wait tradeoff |

### Test 4 — Optimization / what-if

**Questions:** Prioritize power / steals / pitching / upside

| Result | **PASS** |
|--------|----------|
| Verified | Four distinct what-if responses (not identical recommendations) |

### Test 5 — Sleepers

**Question:** Should I take this sleeper?

| Result | **PASS** |
|--------|----------|
| Stub | Sleeper take **Junior Caminero**; 5 drafted exclusions; roster needs C/SS |

### Test 6 — Valuation / Trend

**Questions:** Is this player undervalued? / How risky is this pick?

| Page | Result | Context |
|------|--------|---------|
| Trend Value | **PASS** | trend_summary (slope 2.1, R² 0.55), draft_status for Junior Caminero, canonical_drafted_players |
| Valuation | **PASS** | valuation_snapshot (score 0.84), draft_status, canonical_drafted_players |

## Context audit — Draft Assistant (all requirements present)

| Requirement | Path | Sample |
|-------------|------|--------|
| canonical_draft_board | `canonical_draft_board` | Aaron Judge @ pick 1 |
| canonical_drafted_players | `drafted_players` | Aaron Judge |
| available_players | `draft_projection.available_players` | Cal Raleigh |
| draft_queue | `draft_queue` | Cal Raleigh |
| watchlist_focus | `watchlist` | Cal Raleigh |
| tracked_players | `tracked_players` | Vladimir Guerrero Jr. |
| user_roster | `roster` | Juan Soto |
| needed_positions | `needed_positions` | C |
| category_needs | `category_needs` | HR |
| position_scarcity | `draft_projection.position_scarcity` | 2.4 |
| recommended_players | `recommended_players` | Cal Raleigh |
| best_available_players | `draft_projection.best_available` | Cal Raleigh |
| scoring_settings | `scoring_settings` | 5x5 Roto |

## Issues found and fixed during this run

| Issue | Impact | Fix |
|-------|--------|-----|
| `available_df or best_available_df` raised on DataFrame | Draft Assistant cache crashed | Explicit `None` check in `cache_draft_assistant_ami_context` |
| Live Draft session lacked canonical board | T1 failed — 0 drafted players | Live scenario inherits full Draft Assistant session |
| Trend/Valuation missing top-level `draft_status` / `canonical_drafted_players` | T6 failed | `_attach_canonical_draft_fields()` + Trend/Valuation branches |
| Draft status only nested in `trend_summary` | Harness false negative | Promote `draft_status` to top-level ctx |

## Weak areas (manual follow-up)

| Area | Status | Notes |
|------|--------|-------|
| **Command Center solver** | Not tested here | User must verify real LLM follows `ami_answer_template` |
| **Optimization depth** | Stub only | What-if stub varies by keyword; solver must use `available_players` metrics to change picks |
| **Live Draft without mock** | Partial | Harness mocks `gather_live_draft_ami_section` when streamlit_app unavailable; production path uses live rec engine |
| **Slider-linked reasoning** | Not implemented | Safe Floor ↔ Upside sliders not wired to AMI context yet |

## Manual verification checklist (user)

After deploy reboot, send these via **Analyze with Applied Math** sidebar:

1. Draft Assistant — *Who should I draft next?* → must cite Cal Raleigh / queue / needs, not Aaron Judge
2. Draft Assistant — *What does my roster need?* → C, SS, HR, SB from your board
3. Live Draft — *I'm on the clock. Who should I take?* → current pick + recommendation
4. Sleepers — *Should I take this sleeper?* → Fantasy Edge + exclusion of drafted players
5. Trend — *Is this player undervalued?* → slope/R² + draft status
6. Valuation — *How risky is this pick?* → Valuation Score + trend component

**Pass:** Answers use your saved board and six-section analyst structure.  
**Fail:** Generic rankings or drafted-player recommendations → capture context JSON from `?dev=1` and report.

## Re-run locally

```bash
python ami_acceptance_harness.py
python -m pytest tests/test_ami_acceptance.py -v
```

Full JSON output: `docs/ami_acceptance_report.json`
