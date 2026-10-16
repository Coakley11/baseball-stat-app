# AMI integration and architecture audit

**Branch:** `feature/ami-foundation` (from foundation checkpoint `dea3bdc`) · **Date:** 2026-10-16 · **Type:** audit and design. No new features, no write actions.

**Inputs audited**

- This branch.
- The Phase C/D fantasy work on `quality/rest-of-app` at `38d1e3e` (Phases C1–C5, D1–D7), read through a disposable detached checkout.
- The sibling `Applied-mathematical-intelligence` repo, read only.

**Labels used throughout**

- **EXISTS**: in code today; on this branch unless it says "Phase C/D".
- **PROPOSED**: a design recommendation.
- **TO BUILD**: work not started.

---

## 0. Summary

1. **Phase C/D is real and mostly reusable read-only, with one structural gap.**
   - The league model is implemented and documented (`docs/FANTASY_LEAGUE_DATA_MODEL.md` on Phase C/D). It covers league context, rosters, eligibility, the season ledger and official standings, waivers, trades and team control.
   - About two thirds of what AMI needs are importable functions.
   - The rest live inside `streamlit_app.py`: `evaluate_trade`, `score_fantasy_rosters_from_stats`, `build_lineup_assistant_scores` and `lineup_diagnosis_report`. They must be moved into modules by the Phase C owner before AMI can reuse them without duplication.
2. **A scratch merge of AMI `dea3bdc` with Phase C/D `38d1e3e` has no textual conflicts.** Three AMI tests fail on the merged tree, and all three are real drift that the tests were meant to catch:
   - D7 changed the Valuation pool;
   - D5 renamed the Standings headings.

   The numeric valuation parity test did **not** catch D7, because it replays AMI's own copy of the page steps. This audit adds a strict pipeline pin that names the D7 step (§8.2).
3. **One Ask AMI box, several internal paths.** Recommended:
   - one question box;
   - an instant read-only path, the current `ami_assistant`;
   - an optional, user-triggered "Get a full analysis" path, which is the existing Baseball Insight → Command Center pipeline;
   - navigation hand-offs;
   - later, confirmed actions.

   The separate ⚾ Baseball Insight text box disappears from view, but its pipeline is kept (§3).
4. **LLM integration** (§4):
   - Keep the deterministic tools as the only source of numbers. The model chooses read-only tools and writes the prose; a validator rejects any number or player that isn't in the tool results, and the deterministic composer is the fallback.
   - At the current Claude prices (cached 2026-10-06), an average question costs roughly **$0.001 on Claude Haiku 5.5, $0.02 on Claude Sonnet 5.5 and $0.05 on Claude Opus 5.5**.
   - Choose the model with an eval, not by price alone.
5. **AMI should explain what the user sees.** Today AMI re-runs page pipelines at defaults. The fix is to move each page's view-building pipeline into one pure function used by both the page and AMI (§7), not to teach AMI more page-specific glue.
6. **The 32 "baseline" test failures are pre-existing test pollution.**
   - QA harness modules put the sibling AMI repo first on `sys.path`.
   - 27 module names exist in both repos, including `streamlit_app` and the `suite_auth`/`suite_storage_*` modules.
   - The running app never inserts that path.
   - A conftest guard is proposed (§8.1).

---

## 1. Current AMI architecture and capability inventory

### 1.1 Two systems that exist today

| | ⚾ Baseball Insight → Command Center (EXISTS) | 💬 Ask AMI (EXISTS on this branch) |
|---|---|---|
| Entry | Sidebar text box `baseball_ami_sidebar.render_baseball_insight_sidebar` | Sidebar fragment `ami_assistant/ui.py` |
| What happens | `suite_analytical_question.submit_analytical_question` builds a page snapshot (`build_submit_context`, `applied_math_context.build_source_state`). It writes an activity event, a resume item and a context blob to Supabase suite tables. The user opens Command Center → the AMI app (`Applied-mathematical-intelligence`, `solve_suite_question`: a regex router plus deterministic solvers). The answer returns as an insight card (`applied_math_return_insight`). | `ami_assistant.engine.ask` runs the allowlisted page context → deterministic router → read-only tools (the pages' own functions) → grounded composer. It answers in about 1–2 s in the browser. |
| Strengths | Long-form "memo" answers, Hall of Fame case analyses, Command Center history and resume, cross-app (Music, Investment) | Instant; live data lookups for any player, range or stat; app help; follow-ups; numbers proven equal to the pages' |
| Weaknesses | Asynchronous (leave the page); answers only from a frozen snapshot; the AMI repo re-derives baseball reasoning in its own solvers (a second analytics path); stores page context in the cloud | Pattern-based understanding; no fantasy-team data yet; no long-form analysis |
| LLM | none | none (provider interface ready) |
| Writes | Suite records (activity, resume, blob); restores widget values on return | none (tested) |

### 1.2 Ask AMI capabilities (EXISTS)

- **App help:**
  - all 17 pages;
  - 14 step-by-step how-tos, each label checked against the page's source;
  - a glossary sourced from `SCORE_TOOLTIPS` and the page guides.
- **Historical stats:** profile, seasons, compare, leaderboards (Leaderboards and Career Totals semantics), trends and trend leaders, valuation and the valuation board.
- **Draft, read-only:** recommendations, explanations, needs and need-vs-best-available. These are read from `_ami_draft_snapshot`, which the draft pages write.
- **Fantasy team:** contracts only. Six tools return `not_wired`.
- **Refused and redirected:**
  - draft, add, drop, trade and lineup requests;
  - live MLB questions;
  - seasons after 2025.

---

## 2. Phase C integration readiness

Everything below was verified in code at `38d1e3e` (Phase C/D). "Side effects" means writes to session state when called.

### 2.1 Capability → authoritative interface

| Capability | Status in Phase C/D | Authoritative function(s) | Inputs | Side effects | Visibility / authorization | AMI can reuse now? |
|---|---|---|---|---|---|---|
| **Active league and team** | EXISTS | `resolved_fantasy_context.resolve_fantasy_context_for_page(session)` → `ResolvedFantasyContext` (`active_team_name`, `team_names`, `league_rosters`, `lineup_config`, `context_fingerprint`, `coherent`); `fantasy_league_context.get_active_league_context(session, respect_source_priority=True)`. Source priority is `fantasy_context_source.resolve_fantasy_context_source` (live draft > temporary override > saved Active League > simulator). | session | **Writes derived caches** (`_resolved_fantasy_context_cache/_diag`, `_workflow_descriptor_*`). `ensure_fantasy_league_context_state` creates an empty store if absent. | Only leagues in the user's own workspace session. Shared leagues are synced into it by page reads. | **Partly.** These are read-only in intent but write caches. Use a copy-on-read wrapper (PROPOSED §5.2), or read `_resolved_fantasy_context_cache` when the page already built it. A pure `peek_*` API from Phase C is TO BUILD. |
| **Who may act for a team** | EXISTS | `fantasy_team_control.resolve_team_control(session, context, team)` → owner / commissioner_proxy / none; `manageable_teams(session, context)` | session, context, team | none | Hosted installs require a signed-in owner; a commissioner may act only for unclaimed seats. | **Yes**, read-only. Needed to scope private data (§2.2) and for future actions. |
| **Rosters** | EXISTS | `context["league_rosters"]` (source of truth); `fantasy_league_context.league_context_roster_dataframe`; `build_roster_stats_from_league_context` | context (+ stats feed) | none | All rosters in a league are visible to its members (Trade Center shows them). | **Yes.** |
| **Position eligibility** | EXISTS (D3) | `fantasy_position_eligibility.eligibility_for_season`, `attach_eligible_positions` (≥10 games this or last season) | season, frame | **Network:** MLB Stats API fielding, cached 6 h | public | **Yes**, but AMI must not trigger the fetch. Read the eligibility already attached to the page's frames, or say "open the page to load". |
| **Roster coverage / open positions** | EXISTS | `fantasy_roster_validation.evaluate_team_roster`, `fantasy_league_context.resolve_context_open_position_needs`, `fantasy_lineup_fill.unfilled_slots` | context, roster frame | none | own team | **Yes.** |
| **Lineups (period snapshots)** | EXISTS (D1–D6) | `fantasy_season_ledger.list_periods`, `get_period`, `period_status`, `current_period_number`, `get_period_lineup(context, n, team)`; legacy `fantasy_weekly_lineup.get_saved_weekly_lineup` | context | none | own team. Other teams' future lineups should stay private until the period starts (PROPOSED rule). | **Yes**, read-only. |
| **Start/sit, lineup scoring** | EXISTS **in monolith** | `streamlit_app.build_lineup_assistant_scores`, `lineup_diagnosis_report` (results cached under `_fantasy_lineup_scores_cache`, `_fantasy_lineup_diagnosis_cache`) | roster stats, format | — | own team | **No import.** Either the page cache (same pattern as the draft snapshot) or the functions moved to a module (TO BUILD, owned by Phase C). |
| **Official standings** | EXISTS (D5) | `fantasy_season_results.official_standings(context)` → (table, finalized period numbers); `period_category_table`; `fantasy_season_ledger.ledger_initialized` | context | none (pure) | league members | **Yes.** It's pure, and it is the standings AMI should cite. |
| **"Current roster snapshot" standings** | EXISTS **in monolith** | `streamlit_app.score_fantasy_rosters_from_stats`, `summarize_team_category_needs` (cached `_fantasy_standings_roster_cache`) | roster stats + current stats feed | — | league members | **No import** (TO BUILD extraction). Must be labeled "not official", as the page does. |
| **Category strengths/weaknesses (in season)** | EXISTS | `fantasy_waiver_wire.analyze_current_team_needs(my_roster, league_rosters_df, categories=)`, `waiver_categories_for_context` | roster frames with current stats | none | own team | **Yes**, given the current stats feed is loaded (`_fantasy_current_hitter_stats`, loaded by Standings/Lineup via MLB API). AMI must not fetch it. |
| **Free agents / waiver advice** | EXISTS (C2) | `build_waiver_pool`, `filter_unrostered_players`, `recommend_adds_personalized`, `recommend_drops_current`, `compute_waiver_transaction_impact`, `waiver_roster_transaction_mode` (cached `_fantasy_waiver_analysis_cache`) | stats pool, projections, context, my roster | none for the recommenders | league-wide pool; recommendations are for own team | **Yes** for read-only recommendations, or read the page's waiver-analysis cache. |
| **Waiver transaction** | EXISTS (write) | `apply_waiver_move_pairs(session, pairs, team=)` | — | **writes rosters, activity, archive** | owner / commissioner proxy | **Never from AMI now.** It has no separate validator: checks are inline, so a pure `validate_waiver_move_pairs` is TO BUILD for confirmed actions (§6). |
| **Trade evaluation (value)** | EXISTS **in monolith** | `streamlit_app.evaluate_trade(my_give, my_get, my_roster, all_rosters, standings, my_team)`, `build_trade_verdict_text` | rosters, standings | — | own team plus partner rosters | **No import** (TO BUILD extraction). Do not reimplement. |
| **Trade legality** | EXISTS (C3) | `fantasy_trade_legality.trade_roster_warnings(context, proposer_team=, recipient_team=, proposer_gives=, proposer_receives=, stats_pool=)` | context | none (pure) | both teams' rosters | **Yes.** |
| **Trade proposals / history** | EXISTS | `fantasy_trade_proposals.get_trade_proposals`, `get_incoming_trade_proposals(session, team)`, `get_outgoing_trade_proposals`, `get_trade_history`, `get_display_status`, `validate_proposal_players` | context, team | none | **Private to the two teams.** Scope to `manageable_teams`. | **Yes**, scoped. |
| **Draft history** | EXISTS | `draft_archive_state.list_draft_archives`, `get_draft_archive`, `archive_roster_dataframe` | session | none | own workspace | **Yes.** |
| **Draft snapshot** | EXISTS (used) | `_ami_draft_snapshot` / `_ami_draft_projection` (written by `cache_draft_assistant_ami_context` / `cache_live_draft_ami_context`) | — | — | own session | **In use.** Staleness check TO BUILD (§7.6). |
| **Head-to-head schedule / matchups** | **NOT IMPLEMENTED** (doc lists it as open) | — | — | — | — | AMI must say it isn't supported. |
| **Pitching categories / points leagues** | **NOT IMPLEMENTED** (hitters only; points leagues have no official table) | — | — | — | — | Say so. |

### 2.2 Authorization boundaries AMI must enforce in the tool layer (PROPOSED)

1. **Workspace.** AMI only reads the current user's session. It never reads Supabase, the shared-league store or another workspace directly. This is already true today and is tested.
2. **League membership.** League-wide data (rosters, official standings, waiver pool) comes only from contexts already in the user's session.
3. **Team-private data.** These require `resolve_team_control(...).mode != "none"` for the team in question:
   - incoming/outgoing trade proposals;
   - pending waiver pairs;
   - unsaved lineup drafts;
   - lineups for periods that haven't started.
4. **Entitlement.** `baseball_monetization` registers `ADVANCED_DRAFT_INTELLIGENCE` ("deeper recommendations, team-needs analysis, roster optimization"), `ML_PREDICTIONS` and `DRAFT_LAB` as Pro features. Nothing is enforced yet (`ENFORCED_PAGE_FEATURES = {}`). Once it is, AMI tools must carry a `feature_id` and check `can_use_feature(current_entitlement(...), feature)`. Otherwise AMI becomes a free path around the paywall. **TO BUILD** before enforcement turns on.
5. **No network from AMI.** Tools must not trigger MLB API fetches (stats feed, eligibility). They read what the pages loaded, or say what to open.

### 2.3 Missing interfaces (TO BUILD, owned by Phase C / page owners, not AMI)

| Need | Why | Suggested shape |
|---|---|---|
| Side-effect-free league resolution | AMI's read-only guarantee | `peek_resolved_fantasy_context(session) -> ResolvedFantasyContext \| None`: no cache writes, no store creation |
| Move `evaluate_trade`, `build_trade_verdict_text` out of the monolith | Trade questions without duplicating math | `fantasy_trade_evaluation.py` (pure), monolith imports it back (same pattern as `lahman_data`) |
| Move `score_fantasy_rosters_from_stats`, `summarize_team_category_needs` | Snapshot standings | `fantasy_standings_snapshot.py` |
| Move `build_lineup_assistant_scores`, `lineup_diagnosis_report` | Start/sit questions | `fantasy_lineup_scoring.py` |
| Pure validators for every write | Confirmed-action dry runs (§6) | `validate_waiver_move_pairs`, `validate_period_lineup_save`, draft-pick validation in `live_draft_pick_commit` |
| A "page view" builder per analytics page | Visible-result consistency (§7) | `build_valuation_view(yearly, params, sync_inputs)` and equivalents |

### 2.4 Merge compatibility (verified)

- `git merge --no-commit dea3bdc + 38d1e3e`, done in a disposable detached checkout: **clean auto-merge**, including `streamlit_app.py`.
- AMI tests on the merged tree: **88 passed, 3 failed**:
  - `test_valuation_page_pipeline`: D7 inserted `valuation_hitter_pool` into the Valuation pipeline.
  - `test_every_listed_control_exists_on_its_page` and `test_every_how_to_step_uses_real_controls`: D5 replaced "Live Fantasy Standings" with "League Standings (official)" (`fantasy_season_results_ui`) and "Current Roster Snapshot (not official standings)".
- Fixes when Phase C/D lands (small, TO BUILD):
  - call `valuation_scores.valuation_hitter_pool` in `ami_assistant/tools/value.valuation_pool`;
  - update the Standings help entry and its `sources`;
  - re-freeze the strict pins.

---

## 3. Recommended unified Ask AMI experience (PROPOSED)

### 3.1 What a fan sees

One box, **"Ask AMI about baseball or this page"**, in the same place on every page. On a phone it opens from an **Ask AMI** button in the page header (§8.5).

1. **Ask anything.** For example: "Compare Judge and Soto", "Why is he ranked this high?", "Who should I start this week?"
2. **Get a quick answer in a couple of seconds.** It comes with a one-line source ("From this app's stats, 1871–2025" / "From your league" / "App help") and two or three suggested follow-ups as tappable chips.
3. **Go deeper when you want.** Questions that need a full write-up get a **"📝 Get a full analysis"** button under the quick answer, for example "make the Hall of Fame case", "should I trade X for Y considering my whole season", or "explain the math". It takes 30–60 s or opens in Command Center, and it is saved to the user's history.
4. **Go do it.** When the answer points to an action, AMI shows **"Open Waiver Wire (shortstops)"**, **"Open Trade Center with these players"** and similar. Each opens the right page pre-filled; the user makes the change there. Later (§6), AMI can prepare the change and show a confirmation card.

No mode switches and no internal names. "Command Center" appears only as where saved analyses live.

### 3.2 Internal pathways behind the one box

```
question ─► Ask AMI engine ─┬─► Quick path (in-app, read-only tools)        → answer now
                            ├─► Deep path (existing Baseball Insight pipeline) → only on "Get a full analysis"
                            ├─► Navigate path (existing page hand-offs)      → only on click
                            └─► Action path (future, §6)                      → proposal + explicit confirm
```

- **Quick path** EXISTS: `ami_assistant`.
- **Deep path** EXISTS, re-wired: the "Get a full analysis" button calls the *same* `submit_analytical_question(...)` the Baseball Insight box calls today.
  - **Add** the quick path's tool results and the resolved players to the payload as authoritative facts, so the deep analysis can't contradict the quick answer's numbers. TO BUILD; it needs the AMI repo to read those fields.
  - The deep path writes to Supabase only on that explicit click, and the button says so.
- **Navigate path** EXISTS in pieces: `navigate_to_page`, `player_trade_handoff`, `player_waiver_handoff`, `apply_pending_page_transfer`. AMI would only emit a hand-off that the user clicks.
- **The ⚾ Baseball Insight text box** stays in code and behind a flag during migration. Once the button covers it, the sidebar shows only Ask AMI. Hall of Fame Case Mode on Career Totals keeps its own button; it already uses the pipeline.
- **When to offer "Get a full analysis":**
  - the router marks a question "analysis" (multi-factor, "why"/"case"/"in depth", trade or season planning);
  - an LLM path (§4) flags it as needing more than its tools can ground;
  - the user asks.

---

## 4. Proposed LLM / tool-calling architecture (PROPOSED)

### 4.1 Principles

1. **Numbers only come from tools.** The model never computes or recalls statistics. It selects read-only tools and phrases their results.
2. **Writes are not tools.** No state-changing function is in the model's tool list. A future `propose_action` tool only creates a pending proposal; execution is a UI button (§6).
3. **The deterministic stack stays.** It is the fallback and the source of eval ground truth.

### 4.2 Request flow

1. The engine builds the narrow `AmiPageContext` and conversation summary (EXISTS).
2. **Fast lane** (EXISTS, deterministic, no model call). The router answers directly when it is confident:
   - help, definitions, how-to;
   - refusals of actions;
   - live-data questions;
   - missing-context replies.

   This should be a large share of traffic, at zero model cost.
3. **Model lane.** Everything else, open-ended questions and multi-step follow-ups, goes to the model with:
   - a frozen system prompt (grounding rules, what AMI is) and the wired read-only tool schemas (`REGISTRY.schemas()`). Both are cached with `cache_control`;
   - the page context and short history;
   - the user question.

   The model calls tools (in parallel where possible). The app executes them in-process with the user's session; authorization is checked in the tool, never in the prompt. The loop is capped at about 3 tool rounds.
4. **Grounding validator** (TO BUILD). Before showing the model's answer, check that:
   - every number appears in the tool results (formatting-tolerant);
   - every player name was returned by a tool;
   - no forbidden claim is made ("I added/traded/drafted…").

   On failure: one repair attempt, then the deterministic composer over the same tool results.
5. **Failures** (TO BUILD):
   - timeout budget of about 8 s, or a 429/5xx after SDK retries → deterministic answer from whatever tools ran, with a small "quick mode" note;
   - a `refusal` stop reason is handled the same way;
   - a circuit breaker trips the model lane off for a few minutes after repeated errors;
   - per-user and per-day question caps, plus a monthly spend cap.
6. **Provider interface** EXISTS: `ami_assistant/provider.py`, `AnswerProvider.compose`. The model adapter is one new class plus a tool-loop runner. Nothing else in AMI changes.

### 4.3 Provider comparison

Claude prices are from the bundled Claude API reference, cached 2026-10-06, per million tokens. Other vendors' prices were **not verified** here.

| Option | Fit | Notes |
|---|---|---|
| **Claude Haiku 5.5** (`claude-haiku-5-5`, $0.10 in / $0.50 out, ≤100K prompt) | Tool selection plus short grounded answers | Cheapest hosted option, with adaptive thinking and strict tool schemas. The likely default for the quick lane, if an eval confirms quality. |
| **Claude Sonnet 5.5** (`claude-sonnet-5-5`, $2 / $10, cache reads $0.20) | Harder multi-step questions, deep-path drafting | `thinking: {type: "disabled"}` is a 400: use low effort, or `between_tools`. Forced `tool_choice` is unsupported: use `auto` plus `strict: true` tools. |
| **Claude Opus 5.5** (`claude-opus-5-5`, $4 / $20) | The most capable; the deep path if quality demands it | Thinking can't be disabled (effort is the control; the default is `medium`). |
| Other hosted APIs (OpenAI, Google) | Comparable small/medium tiers with tool calling | The provider interface allows them. Prices not verified here; compare on the same eval. |
| Self-hosted open-weight models (e.g. via Ollama on a GPU host) | Lowest marginal cost at very high volume | Streamlit Cloud can't host GPUs. A separate GPU server costs more per month than Haiku-tier API usage at this app's likely volume. Weaker tool-calling reliability, and the operations burden. **Not recommended now.** |

**Per-question cost model** (estimate):

- System prompt plus 15 tool schemas: about 7K tokens, cached.
- Question plus context: about 1K tokens.
- Two model calls (tool selection, then answer).
- Tool results: about 3K tokens.
- Output: about 1.1K tokens including thinking.

| Model | Approx. cost / model-lane question | 30,000 model-lane questions / month |
|---|---|---|
| Haiku 5.5 | ≈ $0.001–0.002 | ≈ $35–60 |
| Sonnet 5.5 | ≈ $0.02–0.03 | ≈ $600–900 |
| Opus 5.5 | ≈ $0.05 | ≈ $1,400 |

- Cache writes add roughly $0.02 per 5-minute window per model on Sonnet.
- Fast-lane questions cost $0.
- The deep path, at about 10K output tokens, costs roughly 5–10× a quick question and is user-triggered.

**Latency:** add about 1–4 s for one or two model calls on top of the current ~1.5 s fragment round-trip. Stream the final text so the user sees words quickly.

**Recommendation**

1. Build an eval first: the deterministic suite's questions plus gold tool calls and gold numbers. The existing tests already encode most of it.
2. Trial Haiku 5.5 and Sonnet 5.5 against it.
3. Pick per lane by quality per dollar.
4. Gate the model lane behind a flag and a budget.
5. Decide whether model-lane answers are a Pro feature. This is a product decision.

### 4.4 Credentials, accounts and data sent

- The key lives in `st.secrets["ami_model"]`, the same pattern as the other `st.secrets` blocks. It is read only inside the provider module. It is never placed in session state, never logged, and never shown in diagnostics.
- No key means the model lane is off and the deterministic path runs. This is the default and today's state.
- The model receives only `build_model_payload` (EXISTS: scrubbed context and tool results). Never send:
  - session state;
  - auth/account/billing data;
  - email addresses;
  - another team's private data.
- League and team names do reach the model; the privacy notice must say so.
- Log usage (tokens, latency, model, fallback reason) per request without the question text by default.

---

## 5. Read-only integration plan (PROPOSED → TO BUILD)

### 5.1 Tool set to wire after Phase C lands

| Tool | Backed by | Scope check |
|---|---|---|
| `get_active_league` | resolved context (copy-on-read) | session |
| `get_team_roster(team?)` | `league_rosters` + eligibility already on frames | league member |
| `get_open_positions` | `evaluate_team_roster` / `resolve_context_open_position_needs` | own team |
| `get_lineup(period?)` | `get_period_lineup`, `period_status` | own team (others only after period start) |
| `get_official_standings` | `official_standings` | league member |
| `get_category_needs` | `analyze_current_team_needs` (needs loaded stats feed) | own team |
| `get_waiver_recommendations(position?)` | `recommend_adds_personalized` / `recommend_drops_current`, or the waiver page cache | own team |
| `check_trade_legality(give, get, partner)` | `trade_roster_warnings` | own team plus partner |
| `get_trade_offers` | `get_incoming/outgoing_trade_proposals` | teams in `manageable_teams` |
| `evaluate_trade` | **after** the monolith extraction | own team |

### 5.2 Calling Phase C resolvers without writing session state

Wrap the calls in a **copy-on-read session view**: `view = dict(session)`, a shallow copy, so the resolvers' top-level cache writes land in the copy. This keeps the existing "AMI never writes session" test true without changing Phase C code. Nested normalization in `ensure_fantasy_league_context_state` is idempotent (`setdefault`), so it needs no copy. Replace the wrapper with Phase C's `peek_*` API once that exists.

### 5.3 Freshness rule

Every league tool returns `context_fingerprint` and the source label (official / snapshot / page cache with timestamp). Answers say which.

---

## 6. Future confirmed-action architecture (PROPOSED, not started)

Order of introduction, lowest risk first:

1. draft queue add;
2. set a future period's lineup;
3. waiver add/drop;
4. trade proposal (send, never accept);
5. live-draft pick.

**Flow**

1. **Propose.** The model or router emits `propose_action(kind, params)`. The server creates an `ActionProposal`:
   - id;
   - kind;
   - params;
   - `context_fingerprint`;
   - the acting team;
   - a human summary;
   - an expiry (about 2 minutes).

   Nothing changes yet.
2. **Dry run.** Call the canonical **validator**:
   - `validate_proposal_players` / `trade_roster_warnings`;
   - `validate_weekly_lineup` / ledger lock rules;
   - `waiver_roster_transaction_mode` plus a pure `validate_waiver_move_pairs` (TO BUILD);
   - the pick validation in `live_draft_pick_commit`.

   Show the exact before/after and any warnings.
3. **Confirm.** The user clicks **Confirm** on a card. A typed "yes" is never enough; models can't click.
4. **Execute.** The button's callback:
   1. re-resolves the context and refuses if the fingerprint changed;
   2. checks `resolve_team_control(...)` (owner or allowed proxy) and the entitlement;
   3. calls the **same** canonical function as the UI: `apply_waiver_move_pairs`, `create_trade_proposal`, `save_period_lineup`, the queue and pick functions;
   4. uses the proposal id as an idempotency key against Streamlit reruns and double clicks.
5. **Record.** Write to `league_activity` with `acting_as` / `via: "ami"` plus the proposal id, the same log that commissioner-proxy actions use. Show the canonical function's actual result, never a model-written claim of success.
6. **Never:**
   - accept or decline a trade for the user;
   - act for a claimed team the user doesn't own;
   - execute without a fresh confirmation;
   - add a second code path that mutates rosters.

---

## 7. Valuation and page-context consistency

### 7.1 The gap

AMI recomputes page results at default settings and states the difference. The user, however, is looking at a specific filtered view, so AMI should explain *that* view.

| Page | What the page applies that AMI doesn't | Effect |
|---|---|---|
| **Valuation** | Draft-sync removal of drafted players (changes the pool, so every percentile and score); Fantasy Position filter (applied **before** scoring, so it changes scores); roster-need boosts after scoring (changes order); after D7, the `valuation_hitter_pool` ≥10 AB filter (changes percentiles; Witt moves from 207th to 76th) | Different score and rank from the screen |
| **Trend Value** | Draft-sync removal **before** `trend_slopes`, which changes the window's league rate used for rate-stat shrinkage, so rate slopes differ slightly; position filter (percentile pool); research boosts (sort); one-season players shown as 0.0 Δ | Slightly different rate slopes and percentiles |
| **Leaderboards** | User stat minimums (`leaders_*_min`), a manual AB override (`leaders_ab_qualification_mode`), custom weights (`leaders_w_*`, Score column), Top N | Different list when the user changed filters |
| **Career Totals** | Batting hand, franchise/league, position mode and selection, by-team toggle, Hall of Fame filter, stat minimums | Different rows |
| **Historical Explorer** | Single-season rows with season filters. **AMI has no single-season ranking tool**: "best single seasons 2020–2025" becomes a multi-season aggregate | Wrong *kind* of answer |
| **Comparison Tool** | The page's Career Totals table covers the **selected Season Year Range or Age Range**. AMI defaults to full careers unless asked | Different totals |
| **Draft pages** | AMI reads the last snapshot written by a draft page, with no pick/revision check. In shared live drafts, other managers' picks can make it stale | Possibly stale recommendations |
| **ML Predictions, Sleepers** | AMI has no ML tool; Sleepers is a snapshot | — |

### 7.2 Fix (PROPOSED)

1. **One view builder per page, shared by the page and AMI.**
   - Move each page's pipeline (the steps pinned in `PagePipelineStrictPinTests`) into a pure function, e.g. `build_valuation_view(yearly, params, sync)`. Here `params` holds the page's filters (window, games, positions, weights, minimums) and `sync` holds the drafted names and team needs from Phase C resolvers.
   - The page renders its output; AMI calls it with the same params read from `AmiPageContext`. One implementation means no drift. The D7 incident shows why: AMI's replica silently fell behind.
   - Sequence this with page owners, one page at a time, using the same verbatim-move-and-import pattern as `lahman_data`.
2. **Context carries all visible parameters.** Extend `PAGE_KEYS` to every filter the view builder takes. It stays an explicit allowlist.
3. **"Explain this row" uses the page's own output.** Each page publishes a tiny `page view summary` (params, fingerprint, top N displayed rows) at render time. AMI's "why is he ranked this high?" explains those rows, and states which parameter drives the rank.
4. **Defaults stay available,** so a question like "what if I removed the position filter?" works. They are always labeled "with default settings" versus "as on your screen".
5. **Draft snapshot freshness.** Store the board revision / pick index in the snapshot and compare it with the live room. If stale, say "recommendations are from pick N; reopen the draft page".
6. **Historical single-season tool.** Add `get_season_leaderboard` mirroring the Historical Explorer rows and qualification (`qualified_ab(span=False)`).

---

## 8. Test and security findings

### 8.1 The 32 "baseline" failures: root cause and fix

- **Cause.** These QA harness modules call `sys.path.insert(0, <sibling Applied-mathematical-intelligence>)` and never restore it:
  - `ami_hardening_pass._ensure_ami_import`, driven by `tests/test_ami_hardening.py`, is the first insertion in suite order;
  - `ami_answer_quality_audit`;
  - `ami_grounded_answer_audit`;
  - `ami_manual_acceptance`;
  - `ami_deployed_smoke`.

  Afterwards, `import streamlit_app` in later tests loads the **AMI repo's** `streamlit_app.py`; the probe showed `module 'streamlit_app' from '…\applied-mathematical-intelligence\streamlit_app.py'`.
- **Location dependence.** It only reproduces where the sibling folder exists next to the checkout (`_REPO_ROOT.parent / "Applied-mathematical-intelligence"`). A checkout elsewhere doesn't see it. That is why the first baseline (in the scratchpad) and the branch disagreed, and why with the sibling present the baseline fails the same 32.
- **Blast radius.** 27 top-level module names exist in both repos: `streamlit_app`, `suite_auth`, `suite_auth_browser`, `suite_storage_config`, `suite_storage_supabase`, `suite_user`, `suite_user_persistence`, `suite_workspace`, `suite_analytical_question` and others. Any test importing one of them *after* the leak can silently test the other app's code.
- **Production impact: none found.** The running app never calls these insertions. `applied_math_context._ensure_ami_import_path` and `draft_ami_instant_solver` are unused by the app. Streamlit Cloud has no sibling folder.
- **Recommended setup** (TO BUILD; not done here, to avoid unrelated changes):
  1. An autouse fixture in `tests/conftest.py` that snapshots and restores `sys.path`, and evicts from `sys.modules` any of the 27 shared names whose `__file__` is outside this repo.
  2. Mark the sibling-dependent tests (`test_ami_hardening`, `test_ami_answer_quality`, `test_ami_acceptance`) `@pytest.mark.ami_sibling`. Run them in a separate pytest invocation, and only when `AMI_REPO_PATH` is set explicitly.
  3. Change the harnesses to `sys.path.append` plus an explicit `importlib` load of `components.*`, so the sibling can never shadow this repo's modules.
  4. CI runs the default suite with no sibling present.
- **This branch.** `tests/ami_assistant_fixtures.realistic_draft_session` restores `sys.path` defensively. Its earlier comment wrongly blamed the acceptance harness and has been corrected; that harness adds no path.

### 8.2 Tests added or changed in this audit (non-behavioral)

- `PagePipelineStrictPinTests` in `tests/test_ami_assistant_tools.py` freezes the exact list of pool-reassigning statements on the Valuation and Trend Value pages, each annotated with how AMI treats it.
- On the Phase C/D tip it reports exactly `agg_value = valuation_hitter_pool(agg_value[agg_value["G"] >= min_g_value])` as unknown. The older pin found D7 only because a searched line happened to change, and the numeric parity test can't find it at all because it replays AMI's own list.

### 8.3 Session state: ownership and lifecycle

| Prefix / keys | Owner | Lifetime |
|---|---|---|
| `_ami_assistant_conversation`, `_ami_assistant_last`, widget `ami_assistant_question` | Ask AMI (this branch) | session only; not in any persistence allowlist (`baseball_persistent_state` uses explicit key tuples) |
| `_ami_last_send`, `_ami_pending_insight`, `_ami_return_context`, `_ami_dismissed_*`, `_ami_force_insight_render`, … | Baseball Insight hand-off | some persisted via `_INSIGHT_KEYS` / `_HOF_HANDOFF_KEYS` |
| `_ami_draft_snapshot`, `_ami_draft_projection`, `_ami_sleepers_snapshot`, `_ami_trend_*` | draft/research pages (writers); both AMIs (readers) | session; rebuilt on page render |

The shared `_ami_` prefix has two owners.

- **Rule (PROPOSED).** `_ami_assistant_*` belongs to Ask AMI only. The hand-off keeps its existing names. Readers never write page snapshots.
- **Note.** Phase C's data-model doc says "the whole session … is saved". In code, saving is allowlist-based, so AMI's conversation is not saved. The doc wording should be tightened by its owner.

### 8.4 User-data isolation and privacy

- **Ask AMI (EXISTS):**
  - in-session only;
  - reads allowlisted keys;
  - secrets screened;
  - tested against seeded Stripe, Supabase, model keys and password values.
- **Deep path (EXISTS):** stores page context in Supabase suite tables. It must stay an explicit, labeled action in the unified UX.
- **LLM (PROPOSED):** sends scrubbed payloads only. League and team names do reach the model, so disclose that and consider zero-data-retention terms.

### 8.5 Mobile usability

- The panel works at 360–430 px (browser-tested: no overflow, tables 184 px).
- But on phones the sidebar is hidden behind the menu, so Ask AMI is hard to discover.
- **PROPOSED:** an "Ask AMI" button in the phone header, next to M2's "Jump to page" picker (`mobile_nav_m2`), that opens the same fragment in a bottom container.

### 8.6 Performance and caching

- AMI processing: 25–40 ms median, under 0.5 s worst case.
- The browser round-trip is about 1–2 s because the panel is a fragment (it was 3–14 s before that change).
- The trend/valuation memo is keyed by a dataset fingerprint (row count, max season, AB sum).
- **Risk.** If Phase C or other branches add data columns without changing those three values, the memo could serve old results. Add a frame-version constant from `lahman_data` to the key (TO BUILD; low risk).
- An LLM adds 1–4 s; stream the final answer.

### 8.7 Monolith regression risk

- This branch's monolith diff is two verbatim moves (`lahman_data.py`, `page_guides.py`; the three frames were proven identical) plus one guarded panel call.
- **Phase C/D merge:** auto-merges, and the 3 expected AMI test updates are listed in §2.4.
- **Ongoing risk:** AMI tools replicating page glue. The strict pins catch it, and §7.2 removes it.

### 8.8 Command Center integration risks

1. **Contradictory answers.** The AMI repo's solvers re-derive numbers. Pass quick-path tool results as authoritative facts (§3.2) and, over time, have the AMI repo call these tools instead of re-deriving.
2. **Double writes.** If both boxes stay visible, users may send the same question twice.
3. **Shared module names (§8.1)** make cross-repo imports fragile. Never import the AMI repo into the Baseball process at runtime; keep the boundary at the Supabase hand-off.
4. **History expectations.** Quick answers are not saved to Command Center history; deep analyses are. The UI must make that clear.

---

## 9. Prioritized implementation roadmap

Each step is independently shippable; there is no feature work in this audit. Owners are suggestions.

| # | Step | Depends on | Size | Owner |
|---|---|---|---|---|
| 0 | **Land Phase C/D**, then merge it into the AMI branch: adopt `valuation_hitter_pool`, update the Standings help entries and sources, re-freeze the strict pins | Phase C/D accepted into `dev` | S | AMI |
| 1 | **Test isolation:** conftest `sys.path`/module guard, `ami_sibling` marker, harnesses use `append` | — | S | QA |
| 2 | **Extract the monolith fantasy functions** (`evaluate_trade`, the snapshot standings, the lineup scoring/diagnosis) into modules, plus `peek_resolved_fantasy_context` and pure write validators | Phase C | M | Phase C owner |
| 3 | **Read-only fantasy tools** (§5.1) with team-control scoping, copy-on-read, freshness labels; replace the six `not_wired` stubs | 0, 2 | M | AMI |
| 4 | **Entitlement gating** in the AMI tool layer (`feature_id` on tools) | product decision on the Free/Pro split | S | AMI + billing |
| 5 | **Page view builders** for Valuation and Trend Value first, then Leaderboards, Career Totals, Comparison; AMI reads the full page params; add `get_season_leaderboard`; draft-snapshot revision check | page owners | M–L | pages + AMI |
| 6 | **Unified UX:** "Get a full analysis" button on the existing pipeline (with quick-path facts attached), navigation buttons, suggested follow-ups, phone header entry; hide the separate Insight box behind a flag | 3 for fantasy answers | M | AMI + UI |
| 7 | **LLM lane:** eval set from the existing suites → provider adapter behind a flag → grounding validator, fallback, budgets, telemetry → model choice per lane by eval | 6 recommended first | M | AMI |
| 8 | **Confirmed actions** (§6), one at a time: queue → future lineup → waiver → trade proposal → live pick | 2 (validators), 3, 6 | L | AMI + Phase C |

**Blockers right now**

- Phase C/D (`38d1e3e`) is not yet accepted or merged into `dev`.
- The monolith-only fantasy functions need extraction by their owner.
- Product decisions are pending:
  - Pro gating for AMI and for its model lane;
  - the model provider and monthly budget;
  - whether quick answers can be saved to history.
