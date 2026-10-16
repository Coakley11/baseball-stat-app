# AMI assistant — foundation (read-only)

**Branch:** `feature/ami-foundation` (from `0e588e0`) · **Status:** foundation checkpoint for review · **Scope:** read-only.

AMI is meant to become Baseball Explorer's guide across the product. This checkpoint adds an
in-app, read-only AMI layer: an "Ask AMI" sidebar panel backed by a capability map, an app-help
registry, structured tools that call Baseball's own tested functions, a narrow page context,
follow-up memory and a provider-neutral answer interface. It changes no fantasy, draft, league
or account state, and it does not replace the existing Command Center hand-off.

---

## 1. What already existed (audit)

| Piece | Where | Status | What it does |
|---|---|---|---|
| ⚾ Baseball Insight sender | `baseball_ami_sidebar.py`, `suite_analytical_question.py` | Production | Sidebar question box. On send it builds a context snapshot, stores it in the suite's Supabase tables (`suite_saved_items` blobs, `suite_resume_items`, `suite_events`), and the user continues in Command Center. |
| Applied Mathematical Intelligence app | separate repo `Applied-mathematical-intelligence` (`components/applied_math_solvers.solve_suite_question`) | Production (separate app) | Keyword/regex router (`applied_math_problem_router`) plus about 7,000 lines of deterministic solvers that answer from the stored snapshot. |
| Insight return card | `applied_math_return_insight.py` | Production | Shows the AMI answer back inside Baseball. |
| Page snapshot caches | `applied_math_context.py` (`cache_draft_assistant_ami_context`, `cache_live_draft_ami_context`, `cache_fantasy_sleepers_ami_context`, trend/valuation caches) | Production | Pages write their computed state into session keys such as `_ami_draft_snapshot` so a question can be sent with it. |
| Answer framing ("prompts") | `baseball_ami_frame.py`, `ami_guidance` strings in `baseball_ami_pages.py` and `draft_ami_helpers.py` | Production | Instructions and templates for the deterministic solver. They are not LLM prompts. |
| Local "instant" solver | `draft_ami_instant_solver.py` | Prototype, unused | Puts the AMI repo on `sys.path` to solve locally. Nothing in the app calls it. |
| QA harnesses | `ami_acceptance_harness.py`, `ami_*_audit.py`, `ami_hardening_pass.py`, `ami_manual_acceptance.py` | QA tooling | Acceptance and grounding audits for the hand-off pipeline. |
| Page help | `PAGE_GUIDES` + `page_quick_guide.py`, `app_tutorial.py` | Production | Quick Guide cards and the onboarding tour. |
| Live Draft chat | `live_draft_chat*.py` | Production | Chat between people in a league. Not AI. |

**Findings**

- **Model/provider:** none. There is no Anthropic/OpenAI SDK, no model call and no model credentials in this repo or in the AMI repo.
- **Tools/functions:** none. AMI answers from a snapshot frozen at send time. It can't look up an arbitrary player, season or range.
- **Context:** the page snapshots, plus `build_source_state`, which copies every session key that matches a page's state prefixes (`page_state.PAGE_STATE_REGISTRY`). The copy is stored in Supabase.
- **Can't answer:** app how-to questions, ad-hoc stat questions outside the snapshot, follow-ups (each send stands alone), or anything instant (it is a hand-off).
- **Mutation:** sending writes suite records (activity, resume items, context blobs). It doesn't write fantasy state. `gather_draft_ami_snapshot` calls `prepare_live_draft_state(session)`, which normalizes session state as a side effect. Returning from AMI restores page widget values (`apply_source_state_to_session`).
- **Duplication:** the AMI repo re-derives baseball reasoning in its own solvers instead of calling Baseball's analytics. That is a second analytics path.

**Decision:** the hand-off pipeline stays as it is. It serves long-form analysis, Hall of Fame case memos and Command Center history. This branch adds the missing *instant, grounded, read-only* layer inside Baseball. That layer reads the **same** page snapshot keys the hand-off already caches, so draft answers agree between the two paths. Its tool layer is the natural thing for the AMI repo to call later instead of re-deriving numbers. Both entry points sit together in the sidebar.

---

## 2. Capability map (`ami_assistant/capabilities.py`)

| Capability | Status | Examples | Tools |
|---|---|---|---|
| App guidance | **Live** | "What can I do on this page?", "How do I compare two players?", "Where do I make a trade?", "What does Decision Score mean?" | `explain_app_page`, `explain_metric`, `find_feature` |
| Historical analytics | **Live** | compare, career, seasons, leaderboards, trends, valuation, rate-stat qualification | `search_players`, `get_player_profile`, `get_player_seasons`, `compare_players`, `get_leaderboard`, `get_player_trends`, `get_trend_leaders`, `get_player_valuation` |
| Draft intelligence | **Live, read-only from page snapshot** | "Who should I draft next?", "Why is X recommended?", "What positions am I weak at?", "Best available shortstops?", "Need or best available?" | `get_active_draft_context`, `get_draft_recommendations`, `explain_draft_recommendation`, `get_team_needs`, `get_sleepers_busts` |
| Fantasy team intelligence | **Contract only (Phase C)** | "I need a shortstop", "Who should I drop?", "Would this trade help?", "Weakest categories?", "Who should I start?" | `get_active_league`, `get_team_roster`, `get_lineup`, `get_standings`, `get_available_free_agents`, `evaluate_trade` (all return `not_wired`) |
| Future actions | **Declared, disabled** | draft, queue, add, drop, trade, change lineup | none callable (`FUTURE_ACTIONS`) |

**Grounding categories.** Every answer carries one label:

- `app_data` — the app's dataset and calculations, or state the user's pages computed this session.
- `product_help` — the help registry.
- `external_current` — needs live MLB information. AMI says the app's data ends with the latest loaded season (2025) and does not answer from stale data. Questions about seasons after 2025 get the same treatment.

**Future actions** (`FUTURE_ACTIONS`) name the canonical owner each must reuse: `live_draft_pick_commit`/`draft_actions`, `live_draft_queue_persist`, `fantasy_waiver_wire` (Phase C2), `fantasy_trade_proposals` + `fantasy_trade_legality` (Phase C3) and `fantasy_weekly_lineup`. When enabled, each one needs an explicit confirmation step and the same authorization checks as the UI. AMI must never get a second mutation path. `ToolRegistry.register` refuses any tool marked `mutates=True`.

---

## 3. Tool contracts (`ami_assistant/tools/`)

Each tool is a `ToolSpec`: name, capability, description, JSON-schema parameters, the functions it reuses, and `wired`/`mutates` flags. `REGISTRY.schemas()` exports provider-neutral schemas (`name`, `description`, `input_schema`) for wired tools only. A tool returns a `ToolResult(ok, data, error_code, message)`. Error codes: `unknown_player`, `ambiguous_player`, `unavailable_season`, `insufficient_history`, `not_in_pool`, `missing_draft_context`, `missing_active_league`, `not_wired`, `bad_argument`, `internal_error`.

| Tool | Reuses (no formulas re-implemented) |
|---|---|
| `get_leaderboard` | Leaderboards: `leaderboard_aggregation.filter_yearly_for_leaderboards` + `aggregate_leaderboard_career_totals` + `lahman_data.add_rate_stats`. With a position, Career Totals' groupby. `rate_stat_qualification.qualified_ab` for the rate-stat AB minimum. Rates rounded to 3 places before sorting, as the pages do. |
| `compare_players`, `get_player_seasons`, `get_player_profile` | Career Totals aggregation + `add_rate_stats`. Best seasons use `qualified_ab(span=False)` (Historical Explorer's single-season rule). |
| `get_player_trends`, `get_trend_leaders` | `trend_slopes.trend_slopes` over the whole trailing window (needed for the PA-weighted, league-shrunk rate slopes), the page's `G ≥ min_games` pool, and `projection_breakdown.classify_trend_direction`. |
| `get_player_valuation` | The Valuation page pipeline step for step, ending in `valuation_scores.add_valuation_scores`. |
| draft tools | Read `_ami_draft_snapshot` / `_ami_draft_projection` (written by `cache_draft_assistant_ami_context` / `cache_live_draft_ami_context`). Never recompute, never call the gatherers. |
| help tools | `page_guides.PAGE_GUIDES`, `draft_score_display.SCORE_TOOLTIPS`, `mobile_nav_m2.PAGE_GROUPS`, the label-checked registry. |

**Small refactors in the monolith (verbatim moves only):**

- `load_data`'s body and its team/rate helpers moved to `lahman_data.py`. `load_data` stays the cached entry point and delegates. A one-off check executed the original `load_data` from `0e588e0` and confirmed all three frames (`batting`, `yearly`, `people`) are identical.
- `PAGE_GUIDES` moved to `page_guides.py`, so AMI quotes exactly what the Quick Guide cards show.

**Not applied by AMI** (user-specific page options, stated in each answer):

- Draft Room sync removal of drafted players on Trend Value and Valuation.
- Roster-need boosts on Valuation.
- The Fantasy Position filter on Valuation.

---

## 4. Page context (`ami_assistant/context.py`)

`AmiPageContext`: `page`, `players` (dropdown labels; "Name (1990-2008)" disambiguates repeated names), `year_range`, `metric`, `positions`, `position_mode`, `window`, `min_games`, `top_n`, `weight_current`, `weight_trend`, and `draft` (`available`, `current_pick`, `draft_round`, `my_next_pick`, `source_page`).

It is built only from the session keys in `PAGE_KEYS` (plus `_ami_draft_snapshot` on draft pages). AMI never iterates session state. Values are coerced to short strings and numbers and screened by `safety.clean_text`. A test records every key read and fails on anything outside the allowlist. Paywall placeholders (`__MONETIZATION_GATE__`) count as no page.

## 5. Page help (`ami_assistant/page_help.py`, `glossary.py`)

Each page record has:

- purpose, when to use it, outputs and tips, taken from the Quick Guide copy;
- exact control labels;
- typical questions;
- related terms;
- next step;
- navigation: sidebar **Choose Page**, or **Jump to page** + group on phones.

There are 14 step-by-step how-tos: compare, trade, waivers, lineup, Historical Explorer, leaderboards, career totals, trends, valuation, draft help, live draft, active draft, standings and upgrade.

Tests fail if:

- a page in `PAGE_OPTIONS` lacks help;
- any listed control label is missing from that page's own branch of `streamlit_app.py` (or the module it delegates to);
- a glossary definition drifts from its source (`SCORE_TOOLTIPS`, the Valuation guide, the Sleepers column glossary, `add_rate_stats`).

## 6. Questions

**Supported now:**

- page / metric / how-to help;
- player profile and best seasons;
- season lines;
- 2–3 player comparisons over any range, including "power", "speed", "contact", "patience" and "production" focus;
- leaderboards by stat, range and position;
- player trends and trend leaders;
- player valuation and the valuation board;
- draft recommendations, explanations, needs and need-vs-best-available, from the draft page's snapshot;
- sleepers/busts as last shown on that page.

**Answered honestly but not served:**

- fantasy-team questions (roster, waivers, trades, lineup, standings): AMI says the connection waits on Phase C and gives the exact steps on the right page;
- live/current MLB questions and seasons after 2025;
- requests to change anything: refused, with the steps to do it in the UI.

**Clarifies instead of guessing:**

- ambiguous names (e.g. two Frank Thomases);
- unknown names;
- "his" when two players are in play;
- missing selections.

## 7. Follow-ups (`conversation.py`)

The subject of the last stats answer (players, range, stats, position, page) is kept in `session["_ami_assistant_conversation"]`, up to 8 turns. It is in no persistence allowlist, so it is never saved to the cloud workspace.

- "Compare Judge and Soto" → "What about just the last three years?" → "Who had more power?" keeps both players and the narrowed range.
- "Best shortstops over the last five years" → "What about catchers?" → "And by home runs?" keeps the range and changes position, then stat.
- New names replace the subject.

## 8. Provider layer (`provider.py`)

`AnswerProvider.compose(ComposeRequest)` is the only place a model would be called. The default, `DeterministicProvider`, writes grounded template answers: every number and reason comes from a tool result, and players are referred to by name. `build_model_payload` defines exactly what a model adapter would receive:

- grounding rules;
- the question and intent;
- the narrow page context;
- wired tool schemas;
- tool results, scrubbed.

No adapter is included, because no model or credentials exist to test one against.

## 9. Security and privacy

- Read-only by construction. No mutating tool can be registered. Future actions are declarations only. Fantasy tools are unwired and not offered to a model.
- A static test bans AMI imports of storage, auth, billing, network, model-SDK and transaction modules. It also forbids tools from writing to `session`. A runtime test proves draft Q&A leaves session state identical.
- Secrets are screened (Stripe keys and ids, JWTs, Supabase keys, model keys, DB URLs, private keys, password assignments, file paths) in context, draft snapshot text and payloads. A test seeds all of them and checks the model payload and the visible answer.
- Visibility: AMI reads only the public Lahman dataset and the current user's own session. It reads no other workspace, no Supabase and no shared-league store, so it can't see more than the UI shows that user.

## 10. Data sources

AMI introduces no new source. It uses:

- the Lahman frame the app already loads;
- page snapshots, whose market ranks come from the FantasyPros exports the app already uses;
- the app's own copy.

Answers are bounded: leaderboards default to 10 rows with a hard cap of 50, and one player's season table at a time. Answers credit "Lahman Baseball Database (Sean Lahman / SABR)". AMI does not dump datasets.

## 11. Waiting on Phase C (`quality/rest-of-app`)

| AMI contract | Needs from Phase C |
|---|---|
| `get_active_league` | accepted active-league resolver (`resolved_fantasy_context` / `fantasy_league_context`) |
| `get_team_roster` | canonical league roster store + position eligibility |
| `get_lineup` | weekly lineup model (`fantasy_weekly_lineup`, `fantasy_lineup_fill`) |
| `get_standings` | roto scoring with tie splitting and team rates (C4) |
| `get_available_free_agents` | roster-aware waiver recommendations (C2) |
| `evaluate_trade` | trade evaluation + `fantasy_trade_legality` (C3) |
| all future actions | canonical transaction functions + authorization, then an explicit-confirmation UI |

None of these interfaces is guessed here. Each tool returns `not_wired` until it is wired deliberately.

## 12. UI and performance

**Panel.** "💬 Ask AMI" (`ami_assistant/ui.py`) sits in the sidebar just above the ⚾ Baseball Insight sender. It has:

- a question box and an **Ask AMI** button;
- a "Looking at: …" context line;
- the answer with its source line;
- "Earlier in this conversation" and "Clear conversation".

It shows a spinner while working and a warning on an empty question. It is a `st.fragment`, so asking reruns only the panel, never the page's analytics. Any failure shows "AMI is unavailable right now." instead of breaking the page.

**Browser acceptance** (local app, Playwright, 1280 / 430 / 390 / 360 px):

- 25 of 25 questions answered;
- no horizontal page overflow at any width;
- the comparison table is 184 px wide inside the 300 px sidebar.

End-to-end time from click to rendered answer:

| Version | Time |
|---|---|
| Before the fragment change (whole page reran) | 3–14 s |
| After | 0.6–1.9 s |

**In-process timings** (real data, 12 target questions):

| Stage | Cold, median (max) | Warm, median (max) |
|---|---|---|
| Context build | 0.1 ms (0.2) | 0.1 ms (0.3) |
| Routing | 26 ms (44) | 22 ms (35) |
| Tools | 0.5 ms (379, first trend window) | 0.3 ms (84) |
| Compose | 0.2 ms | 0.2 ms |
| **Total** | **37 ms (409)** | **25 ms (111)** |

- The player index is built once per process: about 360 ms.
- Model call time: n/a (no model).
- Standalone CSV load (tests/scripts only; the app reuses its cached frame): about 16–35 s.

## 13. Tests

| File | Covers |
|---|---|
| `tests/test_ami_assistant_routing.py` | synthetic data; resolution, intents, context, follow-ups |
| `tests/test_ami_assistant_tools.py` | real data; parity with page functions compiled from `streamlit_app.py`, page step-order pins, failure states |
| `tests/test_ami_assistant_safety.py` | read-only guarantees, secrets, session untouched |
| `tests/test_ami_assistant_help.py` | every page, every control label real, glossary sources, app wiring |
| `tests/test_ami_assistant_panel.py` | Streamlit `AppTest` of the panel |

**Full-suite regression check.** The full suite at `0e588e0` was compared with this branch, failing test IDs only.

- **New tests:** 76, all passing.
- **New failures:** none.
- **Pre-existing failures:** 32 tests fail in this checkout's location on both the baseline and this branch. The cause is an existing test: `test_ami_hardening.py` puts the sibling `Applied-mathematical-intelligence` repo first on `sys.path`, so later `import streamlit_app` loads that app. This happens wherever that sibling repo exists next to the checkout.
- **Test hygiene:** the new tests restore `sys.path` themselves (`tests/ami_assistant_fixtures.realistic_draft_session`).
