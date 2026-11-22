# Baseball Explorer — Free/Pro feature matrix (authoritative proposal)

**Status:** authoritative proposal, updated with the owner's decisions of 2026-11-22 (second brief). Nothing is enforced: `ENFORCED_PAGE_FEATURES = {}` and
`ENFORCED_FEATURES = frozenset()` (`baseball_monetization.py`), and billing rollout `off`/`preview`
resolves every account to Free while every Pro tool stays open to everyone. A registry entry that
says "Pro" is a *classification*, not a paywall.

Audited code: `origin/dev` `00cb48b` (2026-11-22). Line numbers are `streamlit_app.py` unless a file
is named. This supersedes the tiering in `docs/BASEBALL_FREE_PRO_PLAN.md` /
`BASEBALL_ENTITLEMENTS_STAGE1_PLAN.md` (branch `plan/free-pro-entitlements`) where they conflict;
that plan's gate mechanics (action / effective-settings / result gates, one run snapshot, AMI
capability checks) still apply and are reused below.

**Decision column:** **Owner** = your firm decision (2026-11-22 brief); **Rec** = my
recommendation for you to approve or change; **Open** = undecided, options given.

**Gate kinds** (from the Stage 1 plan): **A** action gate (the operation refuses before
computing) · **B** effective-settings gate (saved Pro settings are kept but not applied for Free) ·
**C** result gate (shared computation runs; only the Pro part of the output is withheld, CSVs too).

---

## 1. Summary

**Pro today = 8 real, implemented capability groups.** Each one already exists in the app and can be
gated without removing anything Free users need:

1. **Saved Draft Strategies** (Owner) — named strategies with their own rankings, pins, notes,
   research, approaches, reuse in any draft, confirmed transfers. Already protected in the
   storage layer (`draft_strategy_store._require_access`).
2. **Draft Lab** (Owner) — computer-drafted 4-team simulations, per-pick verdicts and "Why this
   pick", team score breakdown, roster needs, Best/Questionable picks, full CSV/Excel bundle.
3. **Advanced draft intelligence** (Rec) — Draft Assistant category priorities, 8 ranking modes,
   ML-blend scoring, Selected Player Insight, scarcity heatmap; Draft Room Simulator advanced
   columns and post-draft grades.
4. **Advanced ML Predictions** (Owner: top 25 Free, the rest Pro) — projection tuning, model accuracy check, age
   curve, feature importance, the full prediction list.
5. **Advanced analytics** (Rec) — non-linear trendlines and fit statistics, next-year pairing,
   Relationship Finder and its validation, significance tests, Advanced Trend Intelligence, custom
   leaderboard and valuation weights, Sleepers curve-adjusted list and custom points scoring.
6. **Lineup intelligence** (Owner for the split; Rec for the scope) — Use Suggested Lineup,
   Recommended Starters / Bench-Sit-Watch, Lineup Diagnosis.
7. **Trade intelligence** (Rec) — Find Trade Ideas (with fairness scores), Analyze Exact Trade
   (verdict + per-category impact).
8. **Waiver intelligence** (Rec) — personalized add recommendations (positional need, category
   help, grade); Free keeps the standard recommendations.

Plus **AMI Strategy Coaching** (Owner): AMI questions about your own saved strategies (A1, in Dev).
The A2 research bridge is built and tested but not released, so it is listed as *coming soon*.

**Not implemented — never advertise as included:** premium exports (beyond Draft Lab's), expanded
workspaces, matchup/schedule-aware start/sit, category-targeted start/sit, projected standings
impact of trades/waivers, rest-of-season projections, replacement-level baseline, ML prediction
intervals, Draft Lab "test a saved strategy" / scenario comparison, whole-roster optimization,
AMI A3–A5.

**Free stays complete:** Historical Explorer, Career Totals, Leaderboards, search, standard charts
(scatter with any X/Y + linear trendline), comparisons, trends, valuation, sleepers & busts lists
and Edge Map, Draft Room Simulator, Draft Assistant basics, Live Draft, Global Queue, manual
lineups, every trade and waiver transaction, standard waiver recommendations, roster legality
checks, standings, general Ask AMI, 25 ML predictions.

---

## 2. Matrix

Columns: **Capability · Where · Status · Free today · Proposed · Decision · Why worth paying ·
Gate (kind @ point) · Bypass routes to close · Work + tests.**

### 2.1 Drafting

| Capability | Where | Status | Free today | Proposed | Decision | Why worth paying | Gate | Bypass | Work + tests |
|---|---|---|---|---|---|---|---|---|---|
| Draft Room Simulator (board, assign/undo/reset, import, league setup, rosters, projection summary) | 21408–22306 | built | yes | **Free** | Owner | — | none | — | none |
| Live Draft participation, Live queue (incl. adaptive queue, team needs tab) | live_draft_room_ui, draft_queue_panel.py:420 | built | yes | **Free** | Owner | — | none — never disrupt a live room | — | regression: Live with Free + Pro accounts |
| Global Queue (personal) | draft_strategy_ui.py:142–198 | built | yes | **Free** | Owner | — | none | — | — |
| **Saved Draft Strategies** (create, rank, pin, notes, research, approaches, duplicate, transfers, load into a draft, save back) | draft_strategy_pro_ui.py; draft_queue_panel.py:105/301/370; draft_strategy_in_draft.py:328 | built | yes (preview caption) | **Pro** | Owner | Several reusable plans per league type, each with its own ranking and research | A, already in `draft_strategy_store._require_access` (store-level, covers every entry point) | none found: page, in-draft picker, load/save-back and AMI all read through the store | turn on = add `DRAFT_STRATEGIES` to `ENFORCED_FEATURES`; a strategy already chosen inside a live draft keeps working (draft_plan_source.py:23–35); test downgrade keeps data |
| In-draft approaches (Balanced, Best available, Value, Positional scarcity, Roster-aware) | draft_strategy_in_draft.py:27 | built | yes | **Free** | Owner (approved) | — | none | — | — |
| **Draft Lab** simulation + analysis | 22309–22893 | built | yes | **Pro** | Owner | Auto-drafts a full league so you can rehearse; grades every pick and team | **A @ "Run 4-Team Draft Simulation" (22447) + C @ result tabs**, *not* a page gate (see 3.1) | "Analyze Draft" after a Live draft and resume links land on Draft Lab — show the lock there, keep the Live transfer | split `PAGE_FEATURES` page gate into capability gates; AppTest each handoff |
| Draft Lab "Analyze Draft" for *your own completed Live draft* | draft_archive_ui.py:3906 → draft_lab_handoff | built | yes | **Pro grading and analysis; viewing the draft, its picks, results, saving and ordinary exports stay Free** | Owner | Post-draft grading of your real draft is a strong Pro hook | C @ Draft Lab tabs | — | keep the Live archive CSV/Excel Free (it is your own draft) |
| Draft Assistant basics: needs, answer card, profile cards, default "Roster Fit" order, recommendations table core columns | 19860–21406 | built | yes | **Free** | Owner (approved) | — | none | — | — |
| Category priority overrides + "Positions to prioritize" | 20636–20690, 20572 | built | yes | **Pro** | Owner (approved) | Tailor recommendations to your league's scarce categories | B @ `merge_category_priorities` (20636/20655) | AMI draft tools read the same snapshot | — |
| 7 extra ranking modes (Model Value, Decision Score, Grade, Model/Market Rank, Scarcity, Position) | 20944–20984 | built | yes | **Pro** | Owner (approved) | Rank by the model's value, not just fit | B @ `_da_sort_choice` → force "Roster Fit" | — | — |
| ML-blend scoring weights | 19978–20008 | built | yes | **Pro** | Owner (approved) | — | B **arguments only on this page** — the keys are global and Live/Simulator/Lab read them | must not change Live scoring | unit test: Free page call uses defaults, global keys untouched |
| Selected Player Insight | 21260–21274 (`make_draft_recommendation_insight`, only caller) | built | yes | **Pro** | Owner (approved) | Plain-language "why this player" | A | — | — |
| Scarcity + roster heatmap | 21290–21374 | built | yes | **Pro** | Owner (approved) | Shows where positions dry up | C (hide expander, keep scoring) | — | — |
| Simulator advanced columns (Market/Model Rank, Fantasy Edge, Draft Fit, ML Projection, Expected Value) + pick-log expander | 22085–22114, 22168/22181 | built | yes | **Pro** | Owner (approved) | — | C (drop columns) | pick-log expander exposes the same columns — gate both | — |
| Simulator post-draft roster grades | 22208–22279 | built | yes | **Pro** | Owner (2026-11-05: grades Pro, essentials Free) | — | C | — | — |
| AMI `get_team_needs` | ami_assistant/tools/draft.py:205 | built | yes | **Free** (change mapping) | Rec (open) | — | remove `draft_team_needs` from the Pro capability map | **Mismatch today:** the same needs are Free on three pages | — |
| AMI draft recommendations / explanations | tools/draft.py:118/161 | built | yes | **Pro outside live rooms; Free inside a live room** | Owner (approved) | — | capability gate + snapshot origin tag (Stage 1 plan §3.1) | Live room publishes to the same AMI snapshot | test Free member in a live room |

### 2.2 ML Predictions — **decided: top 25 Free + advanced Pro** (Owner)

| Capability | Where | Status | Proposed | Decision | Gate |
|---|---|---|---|---|---|
| Generate/Refresh, position filter, sort, lookback, min games, scope, min AB, model status | 31721–31767, 31866 | built | **Free** | Owner (approved) | none |
| Prediction list | 31975–32046 | built | **Free: top 25 within the user's filters and sort; Pro: full list** | Owner (approved 2026-11-22) | C: one `.head(25)` inside `_ml_apply_display_view` (5485) caps both tables, both CSVs, the U2 answer (top 5), the insight picker and nav results together |
| Selected-player insight text | 32049 | built | **Free** (within the 25) | Owner (approved) | covered by the cap |
| Projection tuning (style, regression, age, similar-player weight, neighbours, auto-apply, Apply) | 31777–31838 | built | **Pro** | Owner (approved) | B: force defaults into the **arguments** at 31840–31851. `ml_projection_style` is aliased to the global draft style (shared_draft_context.py:52) — never write the key |
| Model Accuracy Check (MAE/R² + CSV) | 31947 | built | **Pro** | Owner (approved) | C |
| Age curve, feature importance | 32059–32078 | built | **Pro** | Owner (approved) | C |
| Prediction intervals / uncertainty | — | **not built** | planned | — | — |

Why the split beats a whole-page gate: Free users get a real taste of the model (25 forecasts, the
U2 answer card) and learn what Pro adds; the cap is one line at one function every display already
uses; no other page or AMI tool reads ML output (AMI refuses projection questions,
router.py:388–393), so there is no bypass.

### 2.3 Research and analytics

| Capability | Where | Status | Proposed | Decision | Why worth paying | Gate | Bypass |
|---|---|---|---|---|---|---|---|
| Historical Explorer, Career Totals, Leaderboards (standard), search, profiles | — | built | **Free** | Owner | — | none | — |
| Scatterplot with any X/Y, colour, size, focused/full view, **linear** trendline | 4421–4471 | built | **Free** | Owner (approved) | — | none | — |
| Other trendline types (Poly2/3, Log, Exp, Auto best fit) + fit statistics (r, R², n, equation) | 4474–4480, 4629–4636 | built | **Pro** | Owner (approved) | Regression modelling | B at the value before `_best_fit_stats` (4602) | Relationship Finder rows set the type directly (3983–3995) — gate the value |
| Next-year pairing ("does this stat predict next season?") | 4483–4521 | built | **Pro** | Owner (approved) | Predictive relationships | B @ 4499 | — |
| Relationship Finder (correlation scan) + "Validate against following year" | 4174–4270 | built | **Pro** | Owner (approved) | Finds which stats move together | A (expander) | — |
| Leaderboards custom weights | 17237–17266 | built | **Pro** | Owner (approved) | Build your own composite score | B before `add_leaderboard_score` | web API `weights=` (baseball_api/services.py:551) — same rule |
| Career HOF "Analyze… with AMI" memo | 16726 → 16818 | built | **Pro** | Owner (approved) | Long-form analytical memo (Command Center cost) | A | resume of past analyses stays viewable |
| Compare Players: year-by-year, totals, trend chart | 17595–17647 | built | **Free** | Owner | — | none | — |
| Compare: Advanced Trend Intelligence | 17710 | built | **Pro** | Owner (approved) | — | C (AMI context built in the same block — split first) | — |
| Compare: significance test (Welch) | 17796–18117 | built | **Pro** | Owner (approved) | Is the difference real or noise? | A (expander) | — |
| Trend Value: table, breakouts/declines, dashboard, chart | 18354–18750 | built | **Free** | Owner | — | none | — |
| Trend Value: Advanced Trend Intelligence | 18864 | built | **Pro** | Owner (approved) | Multi-signal trend read | C | keep the 18652 call (feeds AMI) |
| Trend Value: multivariable regression | — | **not built** | planned | — | — | — | — |
| Valuation: window, position, table, insights | 31347–31583 | built | **Free** | Owner | — | none | — |
| Valuation: custom blend weights (current vs trend) | 31466–31480 | built | **Pro** | Owner (approved) | Your own valuation assumptions | B → 1.0/1.0 | AMI `get_player_valuation` accepts weights (tools/value.py:314–338) — force or gate |
| Valuation: scenario modelling | — | **not built** | planned | — | — | — | — |
| Sleepers & Busts: answer, lists, cutoffs, filters, Edge Map points (market vs model rank) | 19028–19758 | built | **Free** | Owner | — | none | — |
| Sleepers: Edge Map trendline type + fit stats | 19528–19630 | built | **Pro** | Owner (approved) | — | B: force Auto Best Fit | — |
| Sleepers: Curve-Adjusted Sleepers | 19653 | built | **Pro** | Owner (approved) | Sleepers ranked against the fitted curve | C | — |
| Sleepers: custom points scoring | 19267–19279 | built | **Pro** | Owner (approved) | — | B: defaults | — |
| **Available Players Only** / draft-source filtering | 19114–19124 etc. | built | **not a plan control** | Owner | — | never tie to entitlement | — |

### 2.4 Lineups (Start/Sit)

| Capability | Where | Status | Proposed | Decision | Gate |
|---|---|---|---|---|---|
| View, edit, Save, Reset lineup; commissioner proxy edits; lineup status card | fantasy_weekly_lineup_ui.py:738/910/928/627 | built | **Free** | Owner | none (they never call the scoring functions) |
| **Use Suggested Lineup** (position-aware optimization) | :714–721 → suggested_lineup.py:57 | built | **Pro** | Owner (2026-11-05) | A in `apply_suggested_lineup` + button |
| Recommended Starters, Bench/Sit/Watch | fantasy_lineup_management_ui.py:221–350, 721–732 | built | **Pro** | Owner | C |
| Lineup Diagnosis / How to Improve | :358–390 | built | **Pro** | Owner | C |
| Custom points scoring for lineup scoring | :204–219 | built (new) | **Pro** | Owner (approved) | B |
| Actionable Recommendations (with waiver targets) | :636–719 | **partly broken** (see §4) | **Pro** | Owner (approved) | C; personalized waiver adds also come through here (`fantasy_actionable_recommendations.py:213`, :669) — same waiver rule |
| Category standings vs league | :590–614 | built | **Free** | Owner (approved) | none |
| AMI `get_lineup_report` | tools/fantasy.py:514 | built | **Pro** | Owner (approved) | add `plan_capability` |
| Matchup-aware start/sit; category-targeted start/sit; deeper start-A-over-B explanations | — | **not built** | planned | — | — |

### 2.5 Trades

| Capability | Where | Status | Proposed | Decision | Gate |
|---|---|---|---|---|---|
| Pick partner/players, roster legality warnings, Propose, Confirm/send, Accept, Decline, Counter, Cancel, commissioner execution | fantasy_trade_center_ui.py:457/813/872/990/1009; proposals UI | built | **Free** | Owner | none (they never call `evaluate_trade`) |
| **Find Trade Ideas** (targets to acquire / players to move, fairness score /100) | :865 → fantasy_trade_ideas.py:489 | built | **Pro** | Owner ("particularly like") | A |
| **Analyze Exact Trade** (verdict, per-category give/receive/net, helps/hurts) incl. "Analyze This Trade" on offers | fantasy_trade_analysis.py:27–86; :824; proposals_ui:512/562/576 | built | **Pro** | Owner (approved) | A inside `build_trade_analysis_package` |
| AMI `evaluate_trade` | tools/fantasy.py:691 | built | **split:** legality Free, value verdict Pro | Owner (approved) | split the tool |
| Projected standings impact, multi-trade scenarios, AMI trade strategy | — | **not built** | planned | — | — |

Privacy/authorization: no change. League ownership and proposal authorization checks are separate
from these gates and stay as they are.

### 2.6 Waivers

| Capability | Where | Status | Proposed | Decision | Gate |
|---|---|---|---|---|---|
| Waiver pool (rostered players always removed), add/drop picker, projected impact of a move, Confirm Waiver Move, pending queue | fantasy_waiver_wire.py:400–428, 1864; UI :971–1179 | built | **Free** | Owner | none — rostered filtering stays unconditional |
| Standard add recommendations (weak-category stat score) | fantasy_waiver_wire.py:1245 | built | **Free** | Owner (approved) | — |
| **Personalized add recommendations** (positional need, category help, grade, upgrade over your weakest starter) | :1447, :2773 | built | **Pro** | Owner (approved) | B/C inside `compute_waiver_recommendations` (2743): Free gets `recommend_adds_current`; keep `needs` and `waiver_pool` |
| AMI `get_waiver_recommendations` | tools/fantasy.py:780 | built | same rule | Owner (approved) | inside the same function |
| Replacement-level comparison model, rest-of-season projections | — | partial / not built | planned | — | — |

### 2.7 Player Actions (shared popover `player_quick_actions_popover`, 11563 → `dispatch_player_action` 10908)

| Action | Proposed | Decision | Note |
|---|---|---|---|
| Add to Queue, Draft this player, Compare, Trend, Add to Watchlist, Trade Away/Acquire (handoff), Plan Add/Drop (handoff) | **Free** | Owner | basic fantasy actions |
| Projection breakdown (dialog) | **Free** | Owner (approved) | it explains the numbers already shown |
| **Simulate Draft Pick** (roster impact of taking this player) | **Pro** | Owner | It is draft advice. Reachable from 7+ pages, so gate it in `_render_player_action_button_row` / `dispatch_player_action`, not per page |
| "Add to strategy" | — | — | **Does not exist** today (AMI points to the Draft Strategy page) |
| Trade/waiver handoffs → the destination page's Pro tools | follow 2.5 / 2.6 | — | the handoff itself stays Free |

### 2.8 AMI

| Capability | Status | Proposed | Decision |
|---|---|---|---|
| Single Ask AMI: page help, stats, comparisons, trends, leaders, standings, lineup facts, roster eligibility, available players | built | **Free** | Owner |
| AMI Strategy Coaching A1: list/open your saved strategies, compare one to your Global Queue | built, in Dev | **Pro** | Owner |
| AMI A2: where players rank in your selected strategy, "my top two shortstops", strategy depth | built, tested, **not released** | **Pro — coming soon** until released | Owner |
| AMI A3–A5 (propose notes/findings to save, preferences, coaching) | **not built** | planned | — |

### 2.9 Accounts and billing

| Capability | Status | Proposed | Note |
|---|---|---|---|
| Expanded saved workspaces | **not built** | planned — remove from the Upgrade page | registry `EXPANDED_WORKSPACES` has no implementation |
| Premium exports | only Draft Lab's bundle exists | fold into Draft Lab; remove as a separate benefit | Live Draft archive CSV/Excel stays Free |
| Shared League creation (1 Free, more Pro) | built (creation); gate not built | Owner 2026-11-05 | after the shared-league security fixes |

---

## 3. Boundaries and risks found by the audit

### 3.1 Draft Lab must be gated by capability, not by page

`PAGE_FEATURES` maps "Draft Lab / Simulation" to a page gate that swaps the page before it renders
(15138–15141). That would:
- catch the legacy aliases **"Draft Room"** and **"Draft Simulation"** (943–944), which old links
  use for the *Free* simulator;
- dead-end the Free "Analyze Draft" handoff after a Live draft, Home's "Analyze Draft Strategy",
  "Continue Draft Analysis" resume cards and `bb:draft_lab:*` deep links (the gate's Back button goes
  to Historical Explorer);
- risk clearing `session["draft_lab_results"]`, which Free code reads (draft_ui.py:143,
  live_draft_roster_slots.py:503).

Gate the Run button (A) and the analysis tabs (C), show the lock component inside the page, and keep
the shared scoring functions ungated.

### 3.2 Other traps

- **Global session keys:** ML blend (`draft_use_ml_blend`…) and `ml_projection_style` are shared
  with Live/Simulator/Lab. Gates substitute *arguments*; they never write the keys.
- **Saved Pro settings survive a downgrade** (gate kind B): values stay stored and come back on
  upgrade.
- **AMI must follow the same gates** (`plan_capability` + `entitlement_for_capability`), and Free
  Live-room members must keep AMI draft help inside the room.
- **Hiding a button is not authorization:** every gate lives in the operation (A), the effective
  settings (B) or the result (C); tests call the operations directly.

### 3.3 Entitlement and billing inconsistencies

1. **Price:** "$14.99/month" is hard-coded twice (baseball_monetization_ui.py:93, 138). The QA
   Stripe sandbox price (`price_1UYZXe…`, test mode, product "Baseball Pro (QA)") is **$9.99/month**,
   so a QA tester sees $14.99 and pays $9.99. The staging test price (`price_1UOJuh…`) and any live
   price could not be verified from here. **Fix:** show a price only from billing configuration
   (`pro_price_label`, same setting as the billing branch), otherwise "Price shown at secure
   checkout"; before launch, check the label against the Stripe price (read-only).
2. The Upgrade page sells ML Predictions and Draft Lab as Pro "today" while they are open to all and
   unlabelled; it omits Saved Draft Strategies; it lists workspaces/exports with nothing behind them.
3. AMI `get_team_needs` is Pro-mapped while the same needs are Free on three pages.
4. AMI `get_player_valuation` accepts custom weights that the Valuation page would make Pro.
5. The `draft_lab_simulation` and `ml_predictions` capabilities are registered but nothing checks
   them.
6. The billing lifecycle work (scheduled cancellation, return notice, price label, past-due label)
   is on `fix/billing-portal-completion`, **not in Dev**; Dev's Upgrade page predates it.
7. Upgrade page "Back" returns only to `PAGE_FEATURES` pages, otherwise Historical Explorer.

---

## 4. Separate maintenance issues found during the audit (not monetization)

- **Lineup Actionable Recommendations not shown on the main path** — the enriched table is built
  when a waiver pool and needs exist, but `st.dataframe` sits under the `elif` branch
  (fantasy_lineup_management_ui.py:692–719), so it only renders on the fallback path.
- **AMI Draft Assistant context TypeError** — `int(draft_summary.get("your_next_pick", 0))` (21104)
  fails when the key holds `None` (after your last pick / draft complete); AMI's draft context then
  stays stale. Same risk at 21103 (`your_draft_slot`). Fix: `int(x or 0) or None`.
- **Dead "preferred positions" branch** — imports `DRAFT_ASSISTANT_POSITION_WIDGET_KEY`, which
  `fantasy_position_sync.py` does not define (20547–20570).
- **Wasted lineup scoring calls** — fantasy_lineup_management_ui.py:60 and :228.
- **Draft Lab "Test a strategy"** text (draft_tools.py:24) is not backed by code: all four
  simulated teams use the same picker.
- **Dead code** — `fantasy_lineup_assistant_trade_tabs_ui.py`, `suggest_trade_targets` (7631).

---

## 5. Open decisions

Decided on 2026-11-22: ML split, Simulate Draft Pick, Draft Lab grading of Live drafts, the advanced
analytics list, personalized waivers (see section 6). Still open:

1. **AMI `get_team_needs`:** make it Free to match the pages (recommended).
2. **Launch price:** $14.99/month is proposed; the Stripe test prices disagree (section 3.3).
3. **Enforcement:** stays off until the matrix and the enforcement plan are approved.

---

## 6. Owner decisions recorded 2026-11-22 (second brief)

- **ML Predictions:** Free = top 25 predictions within the user's filters and sort; Pro = full list, tuning,
  accuracy check, feature importance, age curve. The cap must apply to every entry point: both result
  tables and both CSVs, the U2 answer card, the selected-player insight picker, nav results / top-3
  transfer — all go through `_ml_apply_display_view` (one slice point).
- **Draft Lab:** Pro. Draft Room Simulator and standard drafting Free. Draft Lab grading/analysis of a
  completed Live draft is Pro (`draft_lab_live_analysis`); viewing the completed Live draft, its picks,
  results, saving it and ordinary exports stay Free. No Pro rule may interfere with taking part in a
  Live draft.
- **Player Actions:** Simulate Draft Pick is Pro (`draft_pick_simulation`), with one gate in the shared
  click handler `_on_simulate_draft_pick_click` so every page and menu applies it the same way. Draft
  Player, Add to Global Queue, Compare, Trend, Watchlist, trade and waiver actions stay Free.
- **Approved Pro:** advanced regression/modelling/specialised charts, Advanced Trend Intelligence and
  deeper Valuation, advanced Sleepers & Busts, sophisticated Draft Assistant recommendations, Saved Draft
  Strategies and AMI Strategy Coaching, advanced Start/Sit and lineup optimisation, trade ideas /
  fairness / roster-impact analysis, personalized waiver recommendations.
- **Free:** standard statistics, historical research, basic charts, normal comparisons, core draft
  recommendations, lineup editing, trading and waiver transactions.
- **Planned items** stay marked planned and are never sold as included.
- **Price:** $14.99/month is the *proposed* price, not production-approved. The page shows only the
  trusted billing configuration's label (see §3.3).
- **Still to decide:** AMI `get_team_needs` (recommend Free, to match the pages); Shared League
  creation limit timing.
