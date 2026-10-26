# WEB-M2 dependency and API-contract assessment

Status: reviewed 2026-10-17. D1–D6 approved with conditions:
- the one-player view stays in the code but is hidden in API mode until Python supports it;
- sample mode is local-development only and blocked in production;
- WEB-M2 changes stay in `web/` and `docs/`;
- no merge or cherry-pick of u4.

Scope: what WEB-M2 needs from the Python side to replace the sample-data adapter with real
responses, what already exists, what is missing, and where the work overlaps other branches.

Everything here was inspected without touching other worktrees: `git log`, `git show` and
`git grep` against branch refs, plus one `git status --no-optional-locks` per worktree. Nothing
was checked out, run or written outside this branch.

## 1. Summary

- **A real read-only Python API already exists, but not on our branch.** It is on
  `ui/u4-migration-readiness` (worktree `baseball-quality-rest`), commits `711daa7` (WEB-PREP1)
  and `a9a80f7` (WEB-PREP2), dated 2026-10-17:
  - `baseball_api/` is a Starlette ASGI app with pydantic v2 models and OpenAPI 3.1.
  - It has six GET routes over the real Lahman data.
  - Parity tests show it equals what the Streamlit pages render.
  - It is not merged into `dev` or into this branch. Our base (`4bc3d30`) has no `baseball_api/`.
- **About 80% of what the WEB-M1 pages need is served today:** rankings, rows, totals, filters,
  qualification numbers, ids, team names, errors and OpenAPI.
- **The missing 20% is mostly answer wording and product configuration.** Today the frontend
  would have to invent these, which the rules forbid:
  - the full answer sentence;
  - a Leaderboards answer;
  - a short, Markdown-free qualification line;
  - a catalog of stats, defaults and filter options;
  - plain-language stat names;
  - pagination or export.

  These are small additions to `baseball_api`, which the API workstream owns (§5).
- **One WEB-M1 feature has no Python source: the "One player" view.** It was a frontend
  addition, not a Streamlit capability. It needs a backend filter, or it gets hidden in API
  mode (decision D2).
- **Real data is ready for integration testing.** The Lahman CSVs are tracked in git and cover
  1871–2025 (128,598 batting rows), so tests can use real, deterministic data pinned to a
  commit.
- **Overlap risk is between other branches, not ours.** The API branch and the AMI branch both
  rewrite the same regions of `streamlit_app.py`. WEB-M2 touches no Python file.

## 2. Branch and worktree landscape (relevant parts)

| Branch (worktree) | State | Relevance to WEB-M2 |
|---|---|---|
| `web/nextjs-foundation` (`baseball-web`) | `6d10ecf`, WEB-M1 done | This workstream. Changes only `web/` and `docs/` |
| `ui/u4-migration-readiness` (`baseball-quality-rest`) | `a9a80f7`; tracked files clean, only runtime `data/` files and an untracked `suite_storage.py` | **Owns the API and contracts.** Same base `4bc3d30`, 5 commits ahead |
| `feature/ami-foundation` (`baseball-ami`) | `c0e8cf5`; `ami_assistant/context.py` being edited | Changes `streamlit_app.py`; AMI reads page context (see §7) |
| `dev` | `56820e6` | Already contained in our base; untouched |
| `quality/*`, release-candidate, presentation, monetization, billing | no commits beyond our base on API-relevant files | none |

API-relevant files changed since `4bc3d30`, by branch: `u1_answers.py`, `rate_stat_qualification.py`,
`leaderboard_aggregation.py`, `baseball_history.py`, `baseball_api/`, `home_page.py`,
`nav_groups.py`, `streamlit_app.py`, `requirements*.txt`, data CSVs.

- **u4:** `baseball_api/*`, `baseball_history.py` (new), `streamlit_app.py` (29 hunks, the
  historical layer extracted), `home_page.py`, `u2_answers.py`, `requirements-api.txt`,
  `docs/NEXTJS_API_CONTRACTS.md`.
- **AMI:** `streamlit_app.py` only (5 hunks).
- **All others:** none.

## 3. What the API serves today (u4 @ `a9a80f7`)

Run with `uvicorn baseball_api.app:app --port 8601`. All routes are `GET /api/v1/…`.

| Route | Returns | Used by WEB-M1 for |
|---|---|---|
| `/health` | status, build, `data_loaded`, `seasons [first, last]` | year bounds (partly), warm-up state |
| `/players/search?q&limit` | `PlayerSearchResult` (`PlayerSummary[]`, `truncated`) | player picker |
| `/players/resolve?name` | `PlayerSummary`, or 409 with candidates | (not needed) |
| `/players/{id}/seasons?start&end&split` | `PlayerSeasonsResult` (seasons by year) | player summary; possibly the timeline |
| `/seasons?start&end&metric&order&limit&bats&positions&position_source&teams&combine&min_ab&qualified&min_X` | `SeasonLeadersResult` | Historical Explorer |
| `/leaderboards?start&end&metric&weights&limit&min_ab&qualified&min_X` | `LeaderboardResult` | Leaderboards |
| `/openapi.json` | OpenAPI 3.1 (6 paths, 29 schemas) | generated TS types |

Properties that suit WEB-M2:

- **Parity with Streamlit is already proven.** Parity tests (`test_web_prep_api_parity.py`,
  `test_web_prep_history_parity.py`) compare the API with the Streamlit pages run through
  `AppTest`: the top 25 Leaderboards rows and the first 200 Historical Explorer rows.
- **Identity is stable.** Players use Lahman `playerID`; teams use franchise `teamID` plus the
  season's own name.
- **Errors use one envelope:** `{"error": {code, message, details?}}`. Responses are strict
  (`extra="forbid"`), never include tracebacks, and accept GET only.
- **The machine can run it.** It has uvicorn 0.51, pydantic 2.13 and Starlette 1.3.1.
  `requirements.txt` pins Starlette 0.52.1 for Streamlit; the API uses only APIs present in
  both versions (noted by the API workstream).
- **Performance (from their doc, warm):**
  - Historical Explorer: about 0.2–0.25 s.
  - Leaderboards: about 0.1 s.
  - Player search: **about 1.4 s for each new query** (fuzzy match over about 24,000 labels).
  - Cold start: the server is up in about 2 s, and the data loads in about 18 s in a background
    thread. A request during that window waits on the load lock.

## 4. Field-by-field fit: WEB-M1 pages vs the API

Legend: ✅ served as needed · 🟡 served, needs mapping or a small change · ❌ missing.

### Historical Explorer

| WEB-M1 needs | API today | Fit |
|---|---|---|
| Normalized query (range, metric, order) | `start`, `end`, `metric`, `order`, `split_mode` | ✅ |
| Ranked rows, rank, player id/name, year, team, position, stats | `rows[]: SeasonRow` | ✅ |
| Seasons matching in total | `total_rows` | ✅ |
| Answer headline | `headline` (from `u1_answers.season_answer`) | ✅ |
| Answer detail sentence ("…the most among the 9,718 seasons shown…") | not returned; `season_answer` already builds it as `body` | ❌ **G2** |
| Context line ("2022 · NYY · RF") | not returned; built as `context` | ❌ **G2** |
| Which stats to show as tiles | not returned; built as `tiles` | ❌ **G2** |
| Qualification line for the chip | `qualification.text` is the long Streamlit caption, with Markdown and a Streamlit control name ("Change it under *Stat minimum filters*") | 🟡 **G4** |
| Qualification numbers and mode | `applies`, `min_ab`, `qualified_ab`, `mode` | ✅ |
| Stat label, kind and precision | `metric: MetricInfo` (label, kind, decimals) | ✅ |
| Plain stat name for sentences ("home runs") | missing (exists as `u1_answers.STAT_NAMES`) | ❌ **G5** |
| Stat list, year bounds and defaults for the controls | only in `invalid_metric.details.allowed` and `/health` | ❌ **G1** |
| Advanced filters (bats, positions, franchise, split, minimums) | served as parameters ✅; option lists missing ❌ | 🟡 **G1** |
| The full season table (Streamlit shows every row) + CSV export | `limit` ≤ 200, no offset, no export | ❌ **G6** |
| "One player" scope (rank one player's seasons) | no `player_id` filter on `/seasons` | ❌ **G7** / decision D2 |
| Below-minimum seasons marked on a player timeline | the API drops them (same as Streamlit); no per-row flag | ❌ **G7** / D2 |
| Chart choice | frontend decides (agreed: visual decisions stay in the frontend) | ✅ by design |

### Leaderboards

| WEB-M1 needs | API today | Fit |
|---|---|---|
| Query, ranked rows (rank, player, stats, score), total | `start`, `end`, `rows[]: LeaderboardRow`, `total_rows` | ✅ |
| Weights behind the score | `weights` | ✅ |
| Answer headline and detail ("Aaron Judge leads 2020–2025 in OPS: …") | **not returned at all**; `u1_answers.leaderboard_answer` builds both | ❌ **G3** |
| Score definition sentence | inside `leaderboard_answer`'s body | ❌ **G3** |
| Qualification line | same issue as Historical Explorer | 🟡 **G4** |
| "N seasons" under each player | not returned | 🟡 use `G` (games) from `StatLine` instead; no new field needed |
| Top N (Streamlit 5–100) | `limit` 1–200 | ✅ |
| CSV export | — | ❌ **G6** (or client-side CSV of returned rows; see §6) |

### Shared

| Need | API today | Fit |
|---|---|---|
| Player search | `/players/search` (min 2 characters) | 🟡 about 1.4 s per new query: **G8** |
| Player by id | via `/players/{id}/seasons` | 🟡 optional **G9** (`/players/{id}`) |
| Error kinds | `invalid_metric`, `invalid_date_range`, `invalid_parameter`, `player_not_found`, `ambiguous_player` → *invalid request*; `data_unavailable` (503), network failure, 5xx → *unavailable*; `internal_error` → *unknown* | ✅ maps onto the WEB-M1 kinds. The mock-only `unsupported` kind disappears in API mode |
| Warm-up | `/health.data_loaded`; requests block about 18 s while loading | 🟡 handled in the frontend (loading state, generous timeout); optional **G11** |
| Generated TS types | OpenAPI 3.1, all `$ref`s resolve | ✅ |
| Cross-origin | CORS off by default (`BASEBALL_API_CORS_ORIGINS` opt-in) | ✅ either way; see D5 |

## 5. Requested API additions (for the API workstream; not implemented here)

All of these reuse functions the pages already call, so no new business logic is needed.

| # | Addition | Source in Python | Priority for WEB-M2 |
|---|---|---|---|
| **G1** | `GET /api/v1/catalog`: year bounds; per-page stat lists with label, plain name, kind and decimals; page defaults (ranges, metric, order, weights); filter option lists (bats values, positions, franchises with ids and names, leagues); minimum-filter columns | `services.SEASON_METRICS` / `LEADERBOARD_METRICS` / `DEFAULT_WEIGHTS`, `baseball_history`, `u1_answers.STAT_NAMES` | **Required.** Otherwise the frontend hard-codes product config |
| **G2** | `SeasonLeadersResult.answer = {headline, body, context, tile_metrics[]}` | `u1_answers.season_answer` (already called; only `headline` is kept) | **Required** |
| **G3** | `LeaderboardResult.answer = {headline, body, podium?}` | `u1_answers.leaderboard_answer` | **Required** |
| **G4** | Surface-neutral qualification copy: a short `summary` ("Qualified hitters · at least 2,349 AB over 2020–2025", the U1 chip) and a plain-text `explanation`, with no Markdown and no Streamlit control names | `u1_answers.qualification_text` logic (today it reads session keys; it needs a pure variant taking the resolved state); `rsq.qualification_caption` | **Required** |
| **G5** | `MetricInfo.name` (plain language) | `u1_answers.STAT_NAMES` | Required (small) |
| **G6** | `offset` on `/seasons` and `/leaderboards` (or a cursor), and/or `format=csv` for export | existing pipelines | Needed for full parity (full table, CSV); not for the first API cut-over |
| **G7** | `player_id` filter on `/seasons`, plus optional `include_below_minimum=true` with a per-row `meets_minimum` flag | `historical_rows` + `apply_stat_minimums` | Only if D2 = keep "One player" |
| **G8** | Faster player search (the candidate prefilter their doc proposes), applied to both surfaces | `draft_player_names.search_draft_pool_names` | Strongly recommended. The frontend can soften it (3+ characters, debounce, abort, cache) but not hide 1.4 s |
| **G9** | `GET /players/{id}` (summary only) | `services._summary` | Optional |
| **G11** | While data is loading, return `503 data_unavailable` with `Retry-After` instead of blocking | `HistoryStore` | Optional |

Wording note for G3: `leaderboard_answer`'s body ends with "Change the weights under Explore
more." That is true only once the web page has weight controls. Either ship weights in
WEB-M2's Explore more, or make the sentence neutral on the Python side.

## 6. Frontend work in WEB-M2 (no Python dependency beyond §5)

1. **HTTP adapter behind the existing `BaseballClient` interface.** Pages don't change; the
   adapter maps API models to the view models.
   - Generate wire types from `/openapi.json` with `openapi-typescript` (a new devDependency,
     D4).
   - Derive view-model field types from the generated ones, so the contract isn't copied by
     hand.
   - Delete hand-written fields that the API now owns.
2. **Same-origin proxy.** Use Next.js `rewrites` from `/api/v1/*` to `BASEBALL_API_ORIGIN`, so
   there's no CORS and the browser sees one origin (D5). The `/health` check drives a
   "warming up" message.
3. **Sample data can't masquerade as real (priority 6).**
   - API mode becomes the default. Fixture mode needs `NEXT_PUBLIC_BASEBALL_DATA_SOURCE=mock`
     and keeps the "Sample data" badge.
   - `next build` fails if the data source is `mock` in a production build.
   - The hand-authored approximate fixtures leave the runtime path. Component tests switch to
     **recorded real API responses** (captured from the API at a pinned commit and labelled
     with it).
   - Mock-only `?mock=` switches stay test-only.
4. **Shorter question bar on phones (priority 3):**
   - Below 640 px the controls collapse to one summary row: "2010–2025 · Home runs · All
     players · Change". Tapping Change opens the editor inline.
   - Target: the answer card starts about 200 px down instead of about 430–590 px.
   - Desktop stays as it is.
   - Frontend only.
5. **Progressive disclosure (priority 4).** Use the served filter parameters (bats, positions,
   franchise/league, split seasons, minimums, Leaderboards weights and Top N) under Explore
   more, closed by default. Full tables and export follow G6.
6. **Parity checklist per page (priority 2):** every U1 capability for Historical Explorer and
   Leaderboards is listed as served, in progress or still Streamlit-only. Streamlit stays the
   complete surface until a web page reaches parity. WEB-M2 removes nothing from Streamlit.
   - **In API scope:** Year Range; Sort by; Order; batting hand; position mode and positions;
     franchise/league; combine split seasons; stat minimums and qualification; summary
     metrics; full table; CSV; top-10 chart; Top N; custom weights.
   - **Not yet served:** Hall of Fame Case Mode; Relationship Finder and scatterplot (the fit
     lines must be computed in Python); "Use these filters in another tool"; the player action
     center; the AMI page snapshot. These stay Streamlit-only for now.
7. **Client-side CSV** of the rows the API returned is acceptable as an interim export: it
   copies the API's values and computes nothing. Full-result export needs G6.

## 7. Overlap and isolation

- **WEB-M2 changes only `web/` and `docs/`.** No Python file, test, requirement or other
  worktree is touched. Contract additions (§5) go to the API workstream through you.
- **Running the API for integration has three options (D1):**
  1. **Recommended:** export `ui/u4-migration-readiness` at a pinned commit (`a9a80f7`) with
     `git archive` into this session's scratchpad (the CSVs are tracked, so the export is
     complete). Run it there with `PYTHONDONTWRITEBYTECODE=1`. This doesn't touch the other
     worktree or branch.
  2. Run uvicorn inside `baseball-quality-rest`. This needs your authorization: even a
     read-only run writes `__pycache__` and logs there.
  3. Merge u4 into this branch. **Not recommended** while it is active, and it needs your
     explicit request.
- **Pinning matters.** The API is pre-release on an unmerged branch, so WEB-M2 records the
  exact API commit it was tested against. A contract change after that needs a deliberate bump
  and type regeneration.
- **Risk for whoever integrates (not this workstream):** `feature/ami-foundation` and
  `ui/u4-migration-readiness` both rewrite `streamlit_app.py`:
  - the import block near line 358;
  - `aggregate_recent_player_totals` near line 2235;
  - the career/primary-team helpers near line 6700.

  Expect conflicts when both reach `dev`. The API extraction is protected by u4's parity tests.
- **AMI dependency, later.** AMI builds its answers from Streamlit page context
  (`ami_assistant/context.py`, `players.py`, `page_help.py`). Once Historical Explorer or
  Leaderboards are used on the web, AMI will need a context contract from the web pages or the
  API. That belongs to the AMI workstream. WEB-M2 keeps only the reserved Ask AMI spot.

## 8. Integration testing with real data

1. **Python side (already exists, u4):** API == Streamlit parity tests over the real Lahman
   data.
2. **Contract:** regenerate TS types from the pinned API's `/openapi.json`. `npm run
   typecheck` fails on drift.
3. **Adapter tests:** map recorded real responses (Judge 2022 62 HR, the real 2020–2025
   leaders, real qualification text and totals) to view models. Assertions compare against the
   recorded JSON, not hand-typed numbers.
4. **End-to-end:** Playwright drives Next against the live pinned API and checks that what is
   displayed equals the API response for the same query. This includes errors
   (`invalid_metric`, out-of-range seasons), warm-up and the 503 path.
5. **Spot check:** a handful of answers compared with the Streamlit page for the same query.

## 9. Decisions needed before WEB-M2 starts

| # | Decision | Recommendation |
|---|---|---|
| D1 | How to run the API during development | Isolated `git archive` export of u4 at `a9a80f7` in the scratchpad |
| D2 | Historical Explorer "One player" scope (a WEB-M1 addition with no Streamlit equivalent) | Keep it only once G7 is served. Until then, hide it in API mode; never rank on the client |
| D3 | Send G1–G5 (required) and G6–G8 (recommended) to the API workstream | Yes; WEB-M2's API cut-over waits on G1–G5 |
| D4 | Add `openapi-typescript` as a devDependency (types only; no runtime client) | Yes |
| D5 | Same-origin proxy (Next `rewrites`) vs browser CORS | Proxy |
| D6 | Fixture policy | API mode by default. Mock mode is explicit, badged and blocked in production builds. Tests use recorded real responses |

## 10. Proposed WEB-M2 order (after review)

1. **M2A (no API needed):** phone question-bar compaction; the fixture policy and build guard;
   the HTTP adapter skeleton, proxy and type generation against the pinned API.
2. **M2B:** Historical Explorer and Leaderboards on the real API for everything already served.
   Answer wording waits on G2–G4. Until those land, the page shows only the API `headline`
   (Historical Explorer) or a neutral, data-free title (Leaderboards); it never composes a
   sentence.
3. **M2C:** advanced filters under Explore more; client-side CSV; full table once G6 lands.
4. **M2D:** a parity review against the U1 checklist and real-data browser acceptance at
   1280 / 430 / 390 / 360.
