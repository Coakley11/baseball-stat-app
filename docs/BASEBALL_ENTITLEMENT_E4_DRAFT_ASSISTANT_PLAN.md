# E4 — advanced Draft Assistant intelligence (plan for approval)

**Status (2026-11-23):** built on `feature/entitlement-e4-draft-assistant` with enforcement off; not active, not deployed. The AMI draft tools are not in the group yet (see §3.3). E4 will be built on its
own branch after E3 is released, with enforcement off, and it will not be combined with the E3
release. The Free/Pro split comes from `docs/BASEBALL_FREE_PRO_MATRIX.md` §2.1 (owner-approved
2026-11-22), and the gate rules come from `BASEBALL_ENTITLEMENT_ENFORCEMENT_PLAN.md` §1.

## 1. What stays Free (owner requirement)

- Ordinary drafting everywhere: Draft Room Simulator board, picks, undo, import, league setup and rosters.
- **Every Live Draft function.** No gate runs inside a live room's pick flow, its recommendations or its queue.
- Basic Draft Assistant recommendations:
  - the page itself, team needs, the answer card and player profile cards;
  - the default **Roster Fit** ranking and the core columns of the recommendations table;
  - automatic category priorities, computed from the roster;
  - in-draft approaches;
  - Player Actions other than Simulate Draft Pick, which is already a separate E2 group.
- Roster information: needs, filled slots, roster totals.
- AMI `get_team_needs`, and **all AMI draft help inside a live room**.

## 2. Pro capabilities — two separate rollout groups (owner decisions 2026-11-23)

**Group `draft_assistant`: advanced Draft Assistant intelligence.**

| Capability | What Pro adds | Gate kind | Gate point (Dev `25f5e3a`) |
|---|---|---|---|
| `draft_ranking_modes` | Every ranking mode except Roster Fit. That is **Model Value** (owner-approved as Pro), Decision Score, Player Grade, Model Rank, Market Rank, Positional Scarcity and Primary Position | **B**: the saved choice `draft_assistant_rec_card_sort` is kept, and Free runs pass "Roster Fit" | the `ranking_mode=` argument to the Draft Assistant scoring cache (~20887) and `order_recommendation_cards(available, _da_sort_choice)` (~21068); the selectbox is disabled while locked |
| `draft_category_priorities` | High/Medium/Low/Off category-priority overrides | **B**: `da_category_priority_overrides` is kept, and Free uses `merge_category_priorities(_auto_priorities, {})`; the selectboxes and "Restore" are disabled while locked | the `_effective_priorities` line (~20716) |
| `draft_recommendation_explanation` (exists) | Selected Player Insight ("why this player") | **A** | `make_draft_recommendation_insight` (~21360) and AMI `explain_draft_recommendation` outside live rooms |
| `draft_scarcity_insights` | Position-scarcity table and roster heatmap | **C**: the expander content is hidden and scoring is unchanged | the expander at ~21376 (it already carries a capability-less Pro note) |
| `draft_recommendations` (exists) | AMI draft recommendations outside a live room | capability gate plus a snapshot origin tag | `ami_assistant/tools/draft.py` |

**Group `draft_simulator`: Draft Room Simulator insights, activated separately (owner).**

| Capability | What Pro adds | Gate kind |
|---|---|---|
| `draft_simulator_insights` | Advanced columns (Market/Model Rank, Fantasy Edge, Draft Fit, ML Projection, Expected Value) in the board **and** the pick-log expander, plus post-draft roster grades | **C**: the columns and grades are dropped; the essentials stay |

Simulator board, player selection, picks, undo, import, setup and rosters stay Free. Listing either group never
locks the other, `simulate_pick`, `draft_lab`, `ml` or `strategies`.

## 3. Constraints found in the audit

1. **Shared scoring.** `apply_draft_pick_scoring` (live_draft_pick_scoring.py) is used by:
   - live recommendations;
   - the AMI cache builder;
   - Draft Lab analysis.

   E4 never gates it. A test will assert that no `allowed_now(` appears in `live_draft_room_ui.py`,
   `live_draft_recommendations.py`, `live_draft_pick_scoring.py`, `draft_ui.py` or `draft_actions.py`.
2. **What is page-local and what is global.** Verified on Dev:
   - **Page-local, safe to gate:** `draft_assistant_rec_card_sort`, `da_category_priority_overrides` and
     `da_effective_category_priorities` are read only by the Draft Assistant page and its own scoring
     cache key (`live_draft_ui_cache`).
   - **Global:** `draft_use_ml_blend`, `draft_ml_blend_weight` and `draft_ml_min_games_signal`. The shared
     projection pool reads them for the Draft Assistant, **Live Draft Room**, Sleepers, Trends, Valuation,
     Comparison and profile cards.
3. **AMI snapshot shared with live rooms.** Each snapshot gets an origin tag. The AMI gates apply only
   when the origin is not a live room.
4. **Downgrade keeps data.** Stored choices stay and are shown disabled while locked; they return with
   Pro. The page snapshot (`page_state.PAGE_STATE_REGISTRY`) already includes these keys. The
   ML-tuning navigation defect found in E3 QA will be re-checked for these keys too.
5. **Dependency resolved.** `feature/draft-assistant-advisor` is a stale local branch. Its 3 commits are
   already in Dev, patch-identical, via `integrate/draft-assistant-dev` (1843f8c, merged 2026-11-04), and
   Dev's `draft_assistant_ranking.py` is byte-identical to it.
   - Current Dev is the intended final Draft Assistant, so E4 builds on Dev and nothing is merged from
     that branch.
   - The local branch can be deleted at the owner's discretion; it is not deleted here.

## 4. Owner decisions (2026-11-23)

1. **Shared settings stay Free.** The ML-blend controls (`draft_use_ml_blend`, `draft_ml_blend_weight`,
   `draft_ml_min_games_signal`) drive Live Draft scoring, so a user never loses control of them when Pro
   ends. A later, *dedicated* Draft-Assistant-only blend control could be Pro, without duplicating the
   scoring engine.
2. **"Positions to prioritize" stays Free.** It is not independently safe: with the position-sync toggle on
   it sets the position filters on the Free research pages (Trend Value, Valuation, ML Predictions,
   Sleepers). Category priorities are Draft Assistant-only and remain Pro.
3. Model Value is Pro; `draft_assistant` and `draft_simulator` stay separate groups.

## 5. Build and test plan

- Registry: the new capabilities under `ADVANCED_DRAFT_INTELLIGENCE`, plus the `draft_assistant` and
  `draft_simulator` groups.
- Unit tests:
  - each group turns on alone, and neither locks the other or any E1–E3 group;
  - B gates pass the defaults and never write the stored keys;
  - C gates drop the columns in the board and in the pick log;
  - A gates refuse before computing;
  - live modules carry no gate;
  - AMI origin: Free gets answers in a live room but not on the page.
- Browser QA (isolated QA project and accounts), with the switch off, `draft_assistant` only, and
  `draft_simulator` only:
  - Free and simulated Pro;
  - downgrade and upgrade in one session;
  - a QA live room with a Free member;
  - phone layout.
- CI against the then-current Dev, then a candidate SHA for separate approval. Nothing is deployed or
  activated without approval.
