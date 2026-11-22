# Baseball Explorer — safe entitlement enforcement plan (Phase 4, for approval)

**Status:** plan only. Enforcement stays OFF (`ENFORCED_PAGE_FEATURES = {}`, `ENFORCED_FEATURES =
frozenset()`). Nothing in this plan is switched on without the owner's separate approval, feature by
feature. Tiering comes from `docs/BASEBALL_FREE_PRO_MATRIX.md` (authoritative). Reuses the gate
mechanics of `plan/free-pro-entitlements` (`BASEBALL_ENTITLEMENTS_STAGE1_PLAN.md`).

## 1. Rules every gate follows

1. **The gate is in the operation, not the button.** Kinds: **A** the operation refuses before it
   computes; **B** saved Pro settings stay stored but Free runs use the defaults (the value is
   substituted where it enters the computation, never by rewriting the session key); **C** a shared
   computation runs unchanged and only the Pro part of its result (and its CSV/Excel) is withheld.
2. **One capability per Pro behaviour,** listed in `CAPABILITY_FEATURES`, checked by
   `entitlement_for_capability` at every entry point: page, Player Action, AMI tool, web API.
3. **One trusted snapshot per run,** resolved server-side from the billing database; never from the
   client. Unready (still loading) → enforced features wait ("Checking your membership…"), they are
   never granted by default.
4. **Never interrupt a Live Draft.** No gate runs inside a live room's pick flow; a strategy copy
   already chosen for a draft keeps working if the plan lapses.
5. **Downgrade keeps data.** Saved strategies, notes and Pro settings are kept and come back on upgrade.
6. **Labels follow the same state** (`baseball_monetization_ui.pro_state`): preview → included /
   locked. A locked control shows the lock component (what it does + Upgrade) instead of a result.

## 2. Gate inventory (current Dev `00cb48b`)

| Feature / capability | Gate | Kind | Every entry point to cover |
|---|---|---|---|
| Saved Draft Strategies `draft_strategy_library` | `draft_strategy_store._require_access` (already store-level) | A | Draft Strategy page, in-draft starting plan / load / save back, AMI A1/A2 tools — all read through the store |
| AMI strategy coaching | same capability (A1/A2 tools declare `plan_capability`) | A | Ask AMI only |
| Draft Lab `draft_lab_simulation` | Run button handler + `simulate_draft_lab`; result tabs | A + C | Draft Lab page, `bb:draft_lab:*` deep links, resume cards, legacy "Draft Room"/"Draft Simulation" aliases (must keep reaching the Free simulator — fix the alias map first) |
| Draft Lab grading of a Live draft `draft_lab_live_analysis` | `push_completed_live_draft_to_lab` / `live_draft_push_analysis_to_session` analysis part | C | Live completion panel "Analyze Draft"; transfer action; viewing/saving/exporting the draft stays Free |
| Simulate Draft Pick `draft_pick_simulation` | `_on_simulate_draft_pick_click` + `build_draft_simulation_result` | A | the shared Player Actions row and the contextual row (7+ pages) |
| Draft Assistant intelligence `draft_recommendations` etc. | `merge_category_priorities`, `_da_sort_choice`, ML-blend args (page-local), `make_draft_recommendation_insight`, scarcity expander, simulator grades/columns | B/A/C | Draft Assistant, Draft Room Simulator, AMI draft tools (outside live rooms) |
| ML Predictions `ml_predictions` | `.head(25)` in `_ml_apply_display_view`; tuning defaults into the pipeline arguments; accuracy/age/importance hidden | C/B | both tables + CSVs, U2 answer card, insight picker, nav results/top-3 transfer (all via the one function) |
| Advanced analytics `advanced_analytics` | trendline type value before `_best_fit_stats`; Relationship Finder expander; significance expander; Advanced Trend Intelligence display; leaderboard/valuation weights; Sleepers curve/points | B/A/C | Historical Explorer, Career, Compare, Trend Value, Leaderboards (+ web API `weights=`), Valuation (+ AMI `get_player_valuation` weights), Sleepers |
| Lineup intelligence `lineup_suggestions`, `lineup_diagnosis` | `apply_suggested_lineup`; Start/Sit and diagnosis blocks | A/C | weekly lineup (incl. commissioner proxy), Lineup Management, AMI `get_lineup_report` |
| Trade intelligence `trade_ideas`, `trade_analysis` | `generate_trade_ideas`; `build_trade_analysis_package` | A | Trade Center buttons, "Analyze This Trade" on offers, AMI `evaluate_trade` (split: legality Free, verdict Pro) |
| Waiver intelligence `waiver_personalized_adds` | inside `compute_waiver_recommendations`: Free gets `recommend_adds_current` | B/C | Waiver Wire, Lineup Actionable Recommendations (`fantasy_actionable_recommendations.py` helpers call `recommend_adds_personalized` directly), AMI waiver tool |

## 3. Technical obstacles found (and how each is handled)

1. **Shared session keys.** ML blend (`draft_use_ml_blend` …) and `ml_projection_style` are read by
   Live, the Simulator and Draft Lab. A gate that rewrote them would change live scoring → substitute
   the *arguments* on the gated page only.
2. **Draft Lab page gate.** The existing page-level gate swaps the page before it renders, which would
   also catch the legacy aliases meant for the Free simulator and dead-end the Free "Analyze Draft"
   handoff → replace with capability gates inside Draft Lab (A + C); fix the alias map.
3. **AMI draft snapshot shared with live rooms.** Enforcing draft intelligence in AMI as-is would block
   AMI help for Free members inside live rooms → tag the snapshot's origin and allow live-room answers.
4. **Simulate Draft Pick is reachable from 7+ pages** through the shared popover → one gate in the
   shared handler, not per page.
5. **Relationship Finder writes the trendline type directly into session** → gate the value where it is
   used, not the widget.
6. **Side doors:** AMI `get_player_valuation` accepts custom weights; the web API accepts leaderboard
   `weights=`; Lineup recommendations call personalized waiver adds directly → gate each.
7. **Exports:** tables are exported by `render_output_table` from whatever they are given → slice/hide
   before rendering so CSV/Excel never carry Pro rows.
8. **No per-run snapshot cache yet.** Today `current_entitlement` resolves per call; with billing
   rollout on, every label and gate would query billing → add the one-snapshot-per-run cache (60 s,
   per user, cleared on sign-in/out and `?billing=` return) **before** enabling anything.
9. **Billing lifecycle code is not in Dev.** Scheduled cancellation, past-due labels, return notice and
   the configurable price label live on `fix/billing-portal-completion`; production needs the amended
   `20261102` migration → merge and verify billing first (Phase 5) before any paid gate.
10. **Mismatch:** AMI `get_team_needs` is Pro-mapped while the same needs are Free on three pages →
    decide (recommend Free) before enforcing draft intelligence.

## 4. Order (each step separately approved; enforcement off between steps)

| Step | Content | Exit test |
|---|---|---|
| E0 | Per-run snapshot cache; `allows / require / effective` helpers; enforcement switch `off / preview / on` (+ per-feature list); lock component wired to `render_pro_note`'s return value | Free/Pro/unready/past-due/scheduled-cancel unit tests; AppTest every page as Free and as Pro with enforcement **off** = no change |
| E1 | Saved Draft Strategies + AMI coaching (store gate already exists) | Free: Global Queue intact, strategies locked, data kept; Pro: unchanged; Live room with a lapsed plan keeps its copy |
| E2 | Draft Lab (+ Live-draft grading) and Simulate Draft Pick | every entry point; aliases reach the simulator; Live drafts unaffected |
| E3 | ML cap 25 + tuning/diagnostics | cap on every entry point incl. CSV and U2 card |
| E4 | Draft Assistant intelligence | Live scoring unchanged; AMI in live rooms works for Free |
| E5 | Advanced analytics | saved Pro settings shown read-only, defaults applied, restored on upgrade |
| E6 | Lineup, trade, waiver + AMI tool splits | mixed league (Pro commissioner, Free member and reverse): every transaction still works |

Each step: focused tests, CI against the then-current Dev, browser QA with QA accounts (Free = qa_danny,
Pro = qa_other via the Stripe test sandbox), then owner approval to switch on.
