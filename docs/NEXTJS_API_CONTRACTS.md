# Next.js migration: Python API contracts and readiness

Status:
- WEB-PREP1 (audit, contracts, typed schemas, the historical layer extracted from
  `streamlit_app.py`) and WEB-PREP2 (a read-only API proof) on `ui/u4-migration-readiness`.
- WEB-M2 API contracts (R1–R8 of the web handoff) on `api/web-m2-contracts`, from `a9a80f7`. See
  [WEB-M2 additions](#web-m2-additions-r1r8).

There is no Next.js code in this repository. A separate frontend worktree owns that.

## Architecture

```
Next.js / React / TypeScript      UI, browser state, navigation, rendering
        │  HTTPS, JSON (OpenAPI-typed)
Python HTTP API (baseball_api)    request validation → service call → typed response
        │  plain function calls
Python business logic             statistics, rankings, ML, valuation, draft intelligence,
                                  fantasy scoring, eligibility, league rules
        │
Persistence / auth / data         Lahman files, workspace store, Supabase auth, billing
```

Rules:

- **Python is authoritative for every number.** TypeScript never re-implements a statistic,
  ranking, model, valuation, draft score, fantasy rule or transaction.
- **The OpenAPI document is the only contract.** It is generated from the pydantic models in
  `baseball_api/schemas.py`. TypeScript types and clients are generated from it
  (e.g. `openapi-typescript`), never written by hand.
- **The API returns business data, not presentation.** It sends numbers, identifiers and the short
  copy the Python side already authors (qualification captions, answer headlines). The frontend
  owns layout. No HTML, no Streamlit markup, no session state.
- **One backend per job.** `baseball_api` is a separate read-only ASGI app. It does not touch:
  - the Streamlit app;
  - the trusted billing service (`baseball_billing_service`, which holds Stripe/Supabase
    secrets).

  It is built on the same stack the repo already uses (Starlette, pinned in `requirements.txt`)
  plus pydantic v2 (already installed through `supabase`). FastAPI was not added: installing it
  would change the shared Python environment. FastAPI could later replace the routing layer
  without changing any contract, since the models are already pydantic.

## B1. Streamlit-coupling audit

Statuses:
- **Ready:** callable without Streamlit, session state or side effects.
- **Thin wrapper needed:** the business function exists but needs a request/response wrapper,
  usually identity → workspace.
- **Coupled:** the logic lives in `streamlit_app.py` page code or `@st.cache_*` functions, or
  mutates session state.

Note that importing `streamlit_app.py` runs the whole app. Anything defined only there is
Coupled until it is moved out.

### Player analytics

| Capability | Authoritative code | Status | What is left |
|---|---|---|---|
| Dataset load (Lahman batting, seasons, people) | `baseball_history.load_history_frames` | **Ready** (moved in WEB-PREP1) | The app keeps a `st.cache_data` wrapper |
| Player search | `baseball_history.build_clean_player_label_map` + `draft_player_names.search_draft_pool_names` | **Ready, served** | Fuzzy matching costs ~1.4 s per new query (see B10) |
| Historical Explorer rows | `baseball_history.historical_rows`, `apply_stat_minimums`, `safe_round_rate_stats`, `rate_stat_qualification` | **Ready, served** (filter block moved out of the page) | Hall of Fame Case Mode stays in the page; `hall_of_fame_data` is pure, so a thin wrapper is enough |
| Player seasons | same as Historical Explorer | **Ready, served** | — |
| Leaderboards | `leaderboard_aggregation`, `baseball_history.add_leaderboard_score`, minimums, qualification | **Ready, served** (score moved out of the page) | — |
| Career Totals | page-local groupby, `add_primary_team_for_career` (`st.cache_data`), `u2_answers.career_answer` (pure) | **Coupled** | Move the career aggregation into a `career_rows(...)` like `historical_rows` |
| Compare Players | page-local assembly, `aggregate_recent_player_totals` (`st.cache_data`), significance test in the monolith; `u2_answers.comparison_answer` and `comparison_state` are pure | **Coupled** | Extract the comparison frame and the significance test |
| Trend Value | `trend_slopes` (pure, playing-time weighting); `compute_player_trend_table` and `aggregate_recent_player_totals` are `st.cache_data` in the monolith; pool via `get_cached_unified_projection_pool_live` | **Thin wrapper after a move** | The two cached functions are plain pandas: move them like the historical layer |
| Valuation | `valuation_scores.add_valuation_scores` (pure); `u2_answers.valuation_answer` (pure); the hitter-only pool (D7) is assembled in the page | **Scoring Ready; pool Coupled** | Extract the pool assembly (window, minimum games, hitter filter) |
| Sleepers & Busts | `load_fantasypros_market_data` (`st.cache_data`), unified projection pool, `apply_draft_pick_scoring` (monolith) | **Coupled** | Same pool/scoring extraction as Draft |
| ML Predictions | `train_random_forest_models` (`st.cache_resource`), `build_*_predictions`, session flags | **Coupled** | Needs a model-lifecycle design (train/cache/version) before serving |

### Draft (read-only)

| Capability | Authoritative code | Status | What is left |
|---|---|---|---|
| Available players / projection pool | `build_draft_lab_player_pool` via `get_cached_unified_projection_pool` (monolith) | **Coupled** | `draft_pool_engine` reaches these by `exec`-ing the top of `streamlit_app.py` under a no-op Streamlit shim. It works offline but is fragile. Extract into modules before serving |
| Decision Score / recommendations | `apply_draft_pick_scoring` (monolith, also via the shim); `recommendation_schema`, `recommendation_dedupe` (pure) | **Coupled** (scoring) / Ready (ranking helpers) | As above. The API must return the ranked pool as computed; it must not re-sort or re-score |
| Team needs | `draft_needs` (pure) | **Ready** | — |
| Draft progress | `draft_room_state.derive_draft_progress`, `draft_board_summary_for_team` (pure over a board) | **Thin wrapper** | Reading the board needs identity → workspace. `get_active_draft_status` has side effects (`prepare_live_draft_state`): don't call it from the API |
| Draft page answers | `u4_answers` (pure) | **Ready** | — |

### Fantasy (read-only)

| Capability | Authoritative code | Status | What is left |
|---|---|---|---|
| Active league, official standings, current-roster snapshot, lineup report, eligibility, trade evaluation, team access | `fantasy_read_api` (+ `fantasy_league_peek.isolated_session_view`) | **Thin wrapper needed** | These read a workspace mapping. The API needs: a verified user (Supabase JWT, as the billing service does) → that user's persisted workspace → `isolated_session_view` (read-only overlay) → the read API → typed models |
| Official standings over a context | `fantasy_season_results.official_standings` (pure) | **Ready** given a league context | — |
| Lineup validation, eligibility, slot filling | `fantasy_weekly_lineup.validate_weekly_lineup`, `fantasy_position_eligibility`, `fantasy_lineup_fill` (pure) | **Ready** | — |
| Trade value and legality | `fantasy_trade_evaluation`, `fantasy_trade_legality.trade_roster_issues` (pure) | **Ready** | Access check through `fantasy_read_api.team_access` |
| Lineup and trade answers | `u3_answers.lineup_answer`, `trade_verdict` (pure) | **Ready** | — |

Write interfaces (saves, moves, trades, invites, draft picks) are intentionally not in scope.

## B2. Endpoints (v1)

All routes are `GET`, under `/api/v1`. "Served" means implemented in the proof. Everything else is
the agreed shape for later phases, and its response model is already in the OpenAPI components.

| Endpoint | Response model | Status |
|---|---|---|
| `GET /health` | `HealthInfo` | Served |
| `GET /catalog` | `Catalog` (control options, labels, defaults) | Served (WEB-M2) |
| `GET /players/search?q=judge&limit=10` | `PlayerSearchResult` | Served |
| `GET /players/resolve?name=Frank Thomas` | `PlayerSummary` (409 `ambiguous_player` lists candidates) | Served |
| `GET /players/{player_id}` | `PlayerSummary` | Served (WEB-M2) |
| `GET /players/{player_id}/seasons?start=&end=&split=team\|combined` | `PlayerSeasonsResult` | Served |
| `GET /seasons?start=&end=&metric=HR&order=desc&limit=25&offset=0&format=json\|csv&bats=&positions=&position_source=season\|career&teams=&combine=&min_ab=&qualified=true&min_HR=…&player_id=&include_below_minimum=` | `SeasonLeadersResult` (Historical Explorer), or its CSV | Served |
| `GET /leaderboards?start=&end=&metric=score&weights=HR:1,RBI:1,SB:1&limit=25&offset=0&format=json\|csv&min_ab=&qualified=true&min_X=…` | `LeaderboardResult`, or its CSV | Served |
| `GET /openapi.json` | OpenAPI 3.1 | Served |
| `GET /players/{player_id}/career?start=&end=` | `CareerSummary` | Planned (after the Career extraction) |
| `POST /players/compare` `{player_ids[], start, end}` | `ComparisonResult` | Planned (read-only POST: the body carries a list) |
| `GET /players/{player_id}/trends?metric=OPS&window=3` | `TrendResult` | Planned |
| `GET /valuation?start=&end=&w_current=&w_trend=&position=&player_id=` | `ValuationResult` | Planned |
| `GET /leagues/active` | `LeagueSummary` | Planned (authenticated) |
| `GET /leagues/{league_id}/standings?kind=official\|snapshot` | `StandingsResult` | Planned (authenticated) |
| `GET /leagues/{league_id}/teams/{team_id}/lineup?period=` | `LineupReport` | Planned (authenticated, team access) |
| `POST /leagues/{league_id}/trades/evaluate` | `TradeEvaluation` | Planned (authenticated, read-only evaluation) |

Defaults match the pages, so a frontend that sends no options sees what Streamlit shows:
- **Historical Explorer:** 2010–last season, sort HR, descending, split seasons separate.
- **Leaderboards:** 2020–last season, sort `score`, weights HR/RBI/SB = 1.
- **Both:** rate-stat rankings use the qualified AB automatically.

## B3. Typed schemas

The models live in `baseball_api/schemas.py`:
- **Served now:** `PlayerSummary`, `PlayerSeason`, `SeasonRow`, `SeasonLeadersResult`,
  `SeasonAnswer`, `LeaderboardResult`, `LeaderboardAnswer`, `Qualification`, `MetricInfo`,
  `StatLine`, `TeamRef`, `PlayerRef`, `HealthInfo`, `Catalog` (with its parts), `ErrorResponse`.
- **Contract-only for later phases:** `CareerSummary`, `ComparisonResult`, `TrendResult`,
  `ValuationResult`, `LeagueSummary`, `StandingsResult`, `LineupReport`, `TradeEvaluation`.

How they behave:
- **Strict.** Models are frozen and `extra="forbid"`, so a response can't silently grow internal
  fields.
- **No raw state.** No DataFrames or session structures are returned. Rows are explicit models,
  and lists are limited to 200 per request.
- **Wire names match the pages.** `StatLine` serializes the doubles and triples keys as `2B` and
  `3B`, same as the app.
- **Required means always sent.** Every response field is always serialized (null when empty), so
  the schema lists every field as required, and generated types say `x: T | null`, not `x?: T`. The
  one exception is `ErrorBody.details`, which is left out when there are none. A test walks real
  responses against the schema in both directions.

## B4. Identity

| Thing | Canonical id | Notes |
|---|---|---|
| Player | Lahman `playerID` (`judgeaa01`) | URLs and state use it. Names and labels are display only. Label = name, plus the career span when two players share a name (`Frank Thomas (1951-1966)`). |
| MLB team | franchise `teamID` the app normalizes to (`NYY`, `CLE`) | Each row also carries the season's historical name (`season_name`: Indians vs Guardians) and league. |
| Fantasy league | `league_context_id` | From `fantasy_read_api.LeagueSummary.league_context_id`. |
| Fantasy team | the league's team key (roster key in `league_rosters`) | Access is decided by `fantasy_team_control` (owner / commissioner proxy). |
| Scoring period | `(league_context_id, period number)` | From the season ledger. A finalized period never changes. |

A renamed player or team doesn't break a frontend URL, because URLs never contain names.

## B5. Errors

Every error is `{"error": {"code", "message", "details?"}}` (`ErrorResponse`):

| Code | HTTP | When |
|---|---|---|
| `player_not_found` | 404 | unknown `player_id` or name |
| `ambiguous_player` | 409 | a name matches several players (`details.candidates`) |
| `invalid_metric` | 422 | stat not offered on that page (`details.allowed`) |
| `invalid_date_range` | 422 | start after end, or outside the data (`details.available`) |
| `invalid_parameter` | 422 | malformed number/flag/list, limit outside 1–200, negative offset, unknown minimum or weight, `min_AB` (use `min_ab`), `include_below_minimum` without `player_id`, `format` not json/csv |
| `no_active_league` | 404 | (planned) the user has no active league |
| `unauthorized_team` | 403 | (planned) not the owner or commissioner proxy |
| `missing_finalized_weeks` | 409 | (planned) official standings requested before any finalized period |
| `data_unavailable` | 503 | the data is still loading (`Retry-After` header, `details.retry_after`), or the data files are missing (no `Retry-After`) |
| `not_found` | 404 | unknown route |
| `internal_error` | 500 | anything unexpected: a generic message, never a traceback; logged server-side |

Unsupported methods get 405.

## B6. Display data vs business data

A ranking response carries what the U1–U4 hierarchy needs to draw its answer card, chart and table:
- the rows (`offset` paging; ranks are absolute);
- `total_rows` (and `ranked_rows` on `/seasons`);
- `metric` metadata (key, label, plain-language `name`, kind, precision, direction);
- `qualification`: applies, min AB, qualified AB, auto/manual, the page's caption (`text`,
  Markdown, Streamlit only), the chip line (`summary`) and a plain-text `explanation`;
- `answer`: the page's answer card (headline, body, context, and the tile metrics on
  `/seasons`).

Visual decisions stay in the frontend: tiles, chart type, colors, layout. Plain-language answer
sentences come from the same pure `u*_answers` functions the pages use, so both surfaces say the
same thing.

## B7–B9. The proof

`baseball_api/` (`app.py` routes and errors, `services.py` business calls, `schemas.py`,
`openapi.py`):

```
uvicorn baseball_api.app:app --port 8601
# optional: BASEBALL_API_CORS_ORIGINS=http://localhost:3000   (CORS is off by default)
```

**Flow.** HTTP request → strict query parsing → `services.*` → the same functions the pages call →
pydantic model → JSON. Each response carries `Server-Timing: business;dur=…, serialize;dur=…`.

**Data load.** Lahman data loads once per process in a background thread at startup.

**OpenAPI.** `GET /api/v1/openapi.json` is an OpenAPI 3.1 document: the 8 API paths and 39 component
schemas. Every `$ref` resolves (tested). The two ranking paths also declare their `text/csv` response,
and every 503 declares `Retry-After`. It is suitable for `openapi-typescript` / `openapi-fetch`.

**Tests:**
- `tests/test_web_prep_history_parity.py`: the moved historical layer equals the original
  `streamlit_app.py` code. The originals are rebuilt from `4bc3d30` by AST span. Covered: the full
  load, aggregators, labels, four Historical Explorer filter combinations, minimums, score, plus a
  negative control.
- `tests/test_web_prep_api_parity.py`: the API equals what the Streamlit pages render, through a
  full `AppTest` run of each page.
  - Leaderboards: the top 25 rows, all 12 columns.
  - Historical Explorer: the first 200 rows, every stat column, names, years, teams.
- `tests/test_web_prep_api.py`:
  - response models validate;
  - identity uses `player_id`;
  - qualification travels with rankings;
  - documented errors and malformed requests;
  - a generic 500 with no leak;
  - security (no paths or secrets, GET only, no CORS or cookies by default);
  - OpenAPI integrity;
  - **no-Streamlit execution:** in a fresh process, every served endpoint (catalog, player, the
    one-player view and both CSV exports included) runs without importing `streamlit` or any
    persistence/auth/billing module. A Python audit hook records zero file writes, renames or
    deletes. A negative control proves the hook sees writes.
- `tests/test_web_m2_api.py`: R1–R8 and the optional items on real data (see below).

## WEB-M2 additions (R1–R8)

Requested in `web/nextjs-foundation:docs/WEB_M2_API_HANDOFF.md` (pinned against `a9a80f7`). All
changes are additive within v1. Every new string comes from the Python functions the pages already
use.

| Item | What the API returns | Source | Proof |
|---|---|---|---|
| **R1** catalog | `GET /catalog`: `seasons {first,last}`; `metrics[]` (key, label, name, kind, decimals, higher_is_better) for every key the API uses; `historical {metrics, defaults, filters}`; `leaderboards {metrics, defaults, weight_stats, weight_bounds, weight_step, limit_bounds, minimum_columns}` | the pages' option lists and builders; the endpoints' own default constants | Option lists are read from the `streamlit_app.py` source and the pages' builder expressions and compared. `/seasons` and `/leaderboards` with no parameters equal the catalog defaults, sent explicitly. Every `teams` value is accepted and matches seasons. |
| **R2** HE answer | `SeasonLeadersResult.answer {headline, body, context, tile_metrics}` (null when nothing matches). `headline` is kept. | `u1_answers.season_answer` (now also returns its tile keys) | AppTest: equals the Streamlit answer card's headline, body, kicker and tiles (labels and values), for HR and OPS. |
| **R3** Leaderboards answer | `LeaderboardResult.answer {headline, body, context}` | `u1_answers.leaderboard_answer(control_hint=False)`: the same text without "Change the weights under Explore more." The page still shows it. | AppTest: headline and kicker equal. The body equals the page's body minus that sentence (score and OBP). No control wording, across metrics and weights. |
| **R4** qualification copy | `Qualification.summary`: the page's chip line. `Qualification.explanation`: plain text. `text` is unchanged. | `u1_answers.qualification_summary` (the pure core `qualification_text` now calls); `rate_stat_qualification.qualification_explanation` (shares the caption's basis wording) | AppTest: `summary` equals the page chip (OPS / OBP; none for counting stats). On 9 cases (auto, manual, zero, short seasons, capped spans) neither field has Markdown or control names. The Streamlit caption is byte-identical. |
| **R5** stat names | `MetricInfo.name` ("home runs", "batting average", "score"; "games" and "season" for G / yearID) | `u1_answers.STAT_NAMES` | Equal for every key. |
| **R6** paging, CSV | `offset` on `/seasons` and `/leaderboards` (ranks stay absolute; `answer` describes the whole result). `format=csv`: the page's export columns and rounding. Without `limit`, every ranked row. | the pages' `render_output_table` CSV path (`format_display_table` rounding, `to_csv(index=False)`) | Pages tile the full ranking. AppTest: the HE CSV's first 250 rows equal the page's table byte for byte, and its row count equals "Rows Returned". The Leaderboards CSV with the page's Top N equals the page's table. |
| **R7** search speed | Same results, faster: the matching takes a median of ~60 ms on 24,000 labels (was ~1.2–1.4 s); `/players/search` takes 114 ms over HTTP (max 139 ms, target 300 ms) | `draft_player_names.search_draft_pool_names`, shared by the API and the app's Draft Room search | Equal to the `a9a80f7` implementation on 108 queries × 2 limits: typos, accents, punctuation, 2-character and multi-word queries, and 60 random label fragments with swapped letters. See below. |
| **R8** one player | `/seasons?player_id=`: the whole page pipeline runs, then rows are limited to that player (ranks 1…n among the player's seasons, same qualification). Without `start`/`end` the range is the player's career. `include_below_minimum=true` (needs `player_id`) appends the player's seasons below the minimums with `meets_minimum: false` and `rank: null`. | `baseball_history.historical_rows` + `apply_stat_minimums` | Equal to the full Historical Explorer result filtered to the `playerID`, for 4 players (split / combined, a stat minimum). Below-minimum seasons have AB under the minimum, and ranked plus below-minimum covers every season once. |
| optional | `GET /players/{id}`: the summary only | `_summary` | Equal to `/players/{id}/seasons`' `player`. |
| optional | While the startup preload holds the data lock, data routes answer `503 data_unavailable` with `Retry-After: 5` instead of blocking for ~18 s. `/health` never waits. | `HistoryStore.get(wait=False)` | Tested with the load lock held. Missing data still returns 503, without `Retry-After`. |

**How R7 stays identical.** Matching is unchanged: a name matches if its normalized key starts
with the query, or any word fuzzily matches the query on its first `len(q)` letters (difflib ratio
≥ 0.75). Three exact shortcuts:
- normalized names are memoized;
- a word's result depends only on its first `len(q)` letters, so each distinct prefix is scored
  once per search;
- before difflib, a prefix is ruled out if it shares too few characters with the query. The ratio
  is matches/len(q), and matches can't exceed the shared character count (difflib's own
  `quick_ratio` bound), so no match is dropped.

The API also warms the name cache when the data loads.

**Regression.** The focused suites (draft, live, import, shared, multiplayer, u1/u2, historical,
leaderboard, career, qualification, web_prep, player names, search, HOF, answers: 268 files) ran on
`a9a80f7` and on this branch:
- **a9a80f7:** 1,960 passed.
- **This branch:** 1,986 passed (the difference is the new tests).
- **Failures:** the same 124 on both, and the same 6 files crash on both. Nothing is new.

**AMI.** This branch does not modify `streamlit_app.py`, so it adds no conflict there beyond what
`a9a80f7` (the WEB-PREP1 extraction) already has with `feature/ami-foundation`. The shared files it
does change (`u1_answers.py`, `rate_stat_qualification.py`, `draft_player_names.py`) are identical
on `a9a80f7` and on `feature/ami-foundation`.

**Notes for the frontend:**
- `historical.metrics` is the page's Sort by list. `/seasons` also accepts `yearID` (API only).
- `positions` follows `position_source`: use `positions_by_source`.
- Bats labels are Left / Right / Both. The page shows the raw L / R / B.
- The CSV never includes below-minimum seasons. The Leaderboards page exports its Top N, so pass
  `limit` for the same file.
- `SeasonRow.rank` is now `integer | null`. It is null only with `include_below_minimum=true`.

## B10. Performance

API, warm, median of 10 requests over real HTTP (uvicorn on the same shared machine). The search
row is 12 different queries, so the memo never answers.

| Endpoint | WEB-PREP2 (total) | WEB-M2 business | WEB-M2 total HTTP (max) |
|---|---|---|---|
| Player search, new query | 1,373 ms | 95 ms | **114 ms** (139) |
| `GET /catalog` | — | 0.3 ms | 4 ms |
| `GET /players/{id}` | — | 2 ms | 15 ms |
| Player seasons (Judge, career) | 76 ms | 42 ms | 49 ms |
| Historical Explorer, HR, 2010–2025, top 25 | 247 ms | 253 ms | 260 ms |
| Historical Explorer, OPS (qualified), top 25 | 200 ms | 197 ms | 201 ms |
| Historical Explorer, OPS, `offset=100&limit=50` | — | 210 ms | 221 ms |
| One player (Judge, OPS, `include_below_minimum`) | — | 150 ms | 159 ms |
| Historical Explorer CSV, every row (24,261 rows, 1.9 MB) | — | 495 ms | 514 ms |
| Leaderboards, score, 2020–2025, top 25 | 96 ms | 71 ms | 78 ms |

Search is faster for two reasons:
- the matching itself is ~60 ms (R7);
- each result's summary now reads that player's rows through an index built at load (1 ms), not
  a scan of the yearly table (13 ms). The summaries are identical on 303 sampled players.

Notes on the table:
- **Cold start.** Server up in 2.3 s; data loaded in 18.3 s, once per process, in the
  background.
- **Repeated searches** are memoized (milliseconds).
- **While loading,** data routes answer 503 with `Retry-After` (WEB-M2) instead of waiting.
- **The same pages in Streamlit,** full load to idle in the same window: Historical Explorer
  22–26 s, Leaderboards 18–33 s.

**Conclusion.** The analytics themselves take 0.1–0.25 s. Nearly all of the 10–30 s a page costs
today is the Streamlit script rerun:
- the whole app script, session restore and sidebar;
- every other widget and chart on the page.

It is not the statistics.

**Search** was the one slow business call: a fuzzy word comparison (difflib) across ~24,000
labels on every query. WEB-M2 R7 made it fast without changing any match (see
[WEB-M2 additions](#web-m2-additions-r1r8)). The change is in the shared function, so the app's
Draft Room search gets it too.

## B11. Security boundary

The read-only API:

- **Holds and reads no secrets.** No service-role key, no Stripe key, no session cookies. It never
  imports the billing or persistence modules (tested).
- **Exposes no paths or state.** Public historical analytics only: no fantasy, account, workspace
  or billing routes (tested), no file paths, no internal session state.
- **Fails closed.** GET only. CORS is off unless origins are configured. Errors are generic, with
  no tracebacks.
- **Answers only fixed queries.** It reads only the Lahman files at the repo root. There is no
  route that takes a path or a workspace id.

Fantasy endpoints must not ship until they have:
- verified identity (Supabase JWT, server-side);
- per-request workspace loading through `isolated_session_view` (read-only);
- team authorization through `fantasy_team_control`.

## B12. Migration order

| Phase | Scope | Python readiness |
|---|---|---|
| **Web M1** | Home + shell / navigation + Historical Explorer (+ player pages) | Ready now (served) |
| **Web M2** | Leaderboards + Career + Compare | Leaderboards ready; extract Career and Compare first |
| **Web M3** | Trend Value + Valuation + Sleepers / ML | Move the trend/recent-totals functions; extract the valuation pool; design the ML model lifecycle |
| **Web M4** | Read-only Draft and Fantasy pages | Replace the `draft_pool_engine` exec shim with real modules; add authenticated read wrappers over `fantasy_read_api` |
| **Web M5** | Authenticated league state and mutations | Write interfaces with the same ownership and validation functions the pages use |
| **Web M6** | Live Draft | Last: its room protocol, timers, auto-pick and shared-room sync are the most stateful part of the app |

## Dependencies

`requirements-api.txt` lists what the API needs. Everything in it is already in `requirements.txt`
or installed through `supabase`.

One mismatch to note: this machine has Starlette 1.3.1 while `requirements.txt` pins 0.52.1 for
Streamlit. The API uses only `Starlette(routes, middleware, lifespan, exception_handlers)`,
`Route`, `CORSMiddleware` and `TestClient`, which exist in both.
