# Next.js frontend foundation (WEB-M1)

Branch `web/nextjs-foundation`, started from `4bc3d30`. Not pushed, not deployed, not merged.

Baseball Explorer is moving gradually from Streamlit to:

```
Next.js + React + TypeScript (web/)  →  Python API  →  existing Python business logic
```

This is not a rewrite. Python stays authoritative for every statistic, ranking, qualification
rule, fantasy rule and persisted state. The web app owns presentation, routing, browser
interaction, frontend state, responsive layout and API consumption. **It must never re-derive
a baseball number.**

WEB-M1 delivers the foundation plus three read-only pages (Home, Historical Explorer,
Leaderboards) on clearly labelled sample data, behind the client boundary the real API will
plug into.

## 1. Where it lives and why

- `web/` holds the whole frontend: its own `package.json`, lockfile, configs and `.gitignore`.
  Nothing Next.js-related sits in the Python root.
- The Streamlit app, `requirements.txt`, the Python tests and `static/` are unchanged. The
  logo was copied into `web/public/brand/`, so neither app depends on the other's folders.
- Turbopack's root is pinned to `web/` (`next.config.ts`), so it never walks the Python tree.

There was no existing JavaScript tooling in the repo (no `package.json`, React or Node).

## 2. Technology

| Concern | Choice | Notes |
|---|---|---|
| Framework | Next.js 16.4.2, App Router, Turbopack | `cacheComponents` and `partialPrefetching` on (create-next-app defaults) |
| UI | React 19.3.0 | |
| Language | TypeScript 6.0.3, `strict` + `noUncheckedIndexedAccess` | TS 7 not used: typescript-eslint supports < 6.1 |
| Lint | ESLint 9 + `eslint-config-next` (core-web-vitals + TS) | ESLint 10 not used: Next's lint plugins cap at 9 |
| Tests | Vitest 4.1.11 + React Testing Library + jsdom | Vitest 5 hit an npm 10 resolver bug; 4.1 is maintained |
| Styling | Plain CSS: tokens in `globals.css`, CSS Modules per area | No Tailwind or UI kit; about 900 lines of CSS in total |
| Charts | No library: small SVG/HTML primitives | See §8 |
| State | URL search params + local component state | No Redux, no global store |
| Runtime | Node 22.23.3 LTS (portable install), npm 11.21 | See `web/README.md` |

Commands (from `web/`): `npm ci`, `npm run dev`, `npm run build`, `npm run typecheck`,
`npm run lint`, `npm test`, or all of them via `npm run check`.

## 3. Routes and navigation

| Route | Page | Status |
|---|---|---|
| `/` | Home | built |
| `/players/historical` | Historical Explorer | built (sample data) |
| `/players/leaderboards` | Leaderboards | built (sample data) |
| anything else | not-found page explaining which pages have moved | built |

Reserved routes (listed in navigation as **Later**, not links, no pages yet):
`/players/career`, `/players/compare`, `/insights/{trend-value,valuation,ml-predictions,sleepers-busts}`,
`/draft/{room,assistant,lab,live}`, `/league/{drafts,standings,lineup,waivers}`, `/account/pricing`.

`src/lib/navigation.ts` is the single navigation map. It uses the accepted U1 sections
(Home · Players · Insights · Draft · My League · Account), with the same 18 entries and order as
`nav_groups.NAV_SECTIONS`. Each entry keeps its Streamlit page key (`streamlitKey`), so old
`?active_page=` links can be redirected once a page moves.

- **Desktop (≥ 960 px):** a fixed left sidebar with logo, grouped sections and an active page
  marked by `aria-current`, a bar and bold weight (never colour alone). The sidebar footer is the
  reserved slot for league context and account controls; today it holds the sample-data note.
- **Phones and tablets (< 960 px):** a compact sticky header (logo, Menu button), a one-line
  sample-data strip, and a grouped full-height menu in a native modal `<dialog>`. The dialog
  gives focus containment, Esc to close and focus return. The menu repeats the current page
  ("You are on …") and closes on navigation. Unfinished pages appear as small "Later" rows
  rather than equal-weight options, which keeps the U1 principle that 17 equal choices is too
  many.
- `AppShell` takes `sidebarFooter`, `headerExtras` and `phoneNotice` slots. Ask AMI, account
  controls and league context go there later without restructuring the shell.

## 4. Page pattern

Every page follows the accepted U1 principle: **answer first → visual summary → obvious next
action → Explore more.**

```
PageHeader (eyebrow, h1, one plain line)       static, prerendered
QuestionBar (seasons, stat, scope)              the URL is the question
AnswerCard (API sentence) + MetricTiles
Qualification chip (API text)
Default visual (ranking bars / season line)
ActionRow: 1–2 next steps (real routes only)
ExploreMore (<details>): advanced controls, full table, notes
```

**Phones (WEB-M2):** below 640 px the QuestionBar collapses to one summary line
("2010–2025 · Home runs · All players") with a Change / Done button (`aria-expanded`). Change
reveals the same controls in place. The bar stays open when the user has to act (an invalid stat
or seasons in the URL, or a player still to choose). The answer card starts at about 290 px on
360–430 px phones, down from 430–590 px. Wider screens always show every control, as in WEB-M1.

**Home** answers "What can I do in Baseball Explorer?" with four task cards
(`home_page.TASKS`). Only Explore Players has buttons (Historical Explorer, Leaderboards).
Compare / Draft / My League say "Coming later · still in the current app" and have no button.
"Try a question" links only to implemented pages. Ask AMI has a reserved, non-interactive spot.
The Streamlit Home's league summary needs auth and league data, so it is not in WEB-M1.

**Historical Explorer** (`?from&to&metric&order&player&scope=player&bats&psrc&pos&team&combine&page`):

- Controls: Seasons (from/to, committed on blur or Enter), Rank by, and Whose seasons
  (All players / One player with player search).
- Answer (all of it the API's): headline, detail sentence, context kicker ("2024 · New York
  Yankees · OF") and the metric tiles it selects (`tile_metrics`). Tiles sit two per row on
  phones and never shrink below about 140 px.
- Qualification chip: the API's short line ("Qualified seasons · at least 437 AB in the season").
  Its plain explanation sits under Explore more.
- Default visual: top-10 seasons as ranking bars (all players), or one player's season line,
  with below-minimum seasons drawn hollow.
- Next steps: "All of {player}'s seasons" or "Best seasons by every player", plus "Leaders over
  {range}".
- Explore more: filters (batting hand, position by season or career, franchise or league, one
  row per player-season, order), the seasons table, Previous / Next over the API's pages, and
  "Download CSV". The table's columns are the API's catalog columns (see below).

**Leaderboards** (`?from&to&metric&top&w`):

- The API's answer: kicker ("Ranked by home runs"), headline and detail; the qualification chip
  and "N qualified hitters ranked".
- Top 3 as player cards with printed rank badges (the medal colour is decoration only) and the
  player's at-bats. The API sends no games or seasons total.
- Top-10 ranking bars.
- Next steps: "{Leader}'s best seasons", "Best single seasons, {range}".
- Explore more: Top N, score weights (Apply), the ranking table in the API's columns, "Download
  CSV" for the Top N shown, and the plain explanation of the minimum.

**Tables are driven by the catalog.** `GET /catalog` lists each page's columns as `{label, field,
metric}`: the header, the dotted path to the value in a row (`stats.HR`, `team.season_name`), and
the stat it belongs to. `ResultTableView` draws exactly those columns in that order; the CSV header
is the same list. TypeScript has no column order of its own; it only formats (rates as `.311`,
counts with separators, years without, missing as a dash).

**CSV is the API's file.** "Download CSV" is a link to the API's `format=csv` response through the
proxy. The proxy forwards `content-type` and `content-disposition`, so the browser saves the file
under the API's name (`historical_explorer.csv`, `leaderboards.csv`). Nothing is rebuilt in the
browser. Historical Explorer exports every ranked row for the question; Leaderboards exports its
Top N.

## 5. States

| State | Historical Explorer | Leaderboards |
|---|---|---|
| Nothing to ask yet | "Choose a player" (One player, none picked) | — |
| Loading | skeleton, `role=status`, `aria-busy` | same |
| Bad URL input (unknown stat, impossible seasons) | "Pick a stat to rank" / "Check the seasons"; no request sent | same |
| API `unavailable` / `unknown` | `role=alert`, Try again (re-runs the same question) | same |
| API `invalid_request` | "That question can't be answered" + reset | same |
| API `unsupported` | "Not available yet" + reset | same |
| No results | "No seasons match" | "No qualified hitters" (cites the rule) or "No players match" |
| Results | answer pattern above | same |

## 6. Data access boundary

```
page component
  → useBaseballQuery(key, client => client.getX(query))    lib/api/useBaseballQuery.ts
  → BaseballClient interface                                lib/api/client.ts
  → HTTP adapter (default, WEB-M2)                          lib/api/http/ (generated wire types)
      → same-origin proxy /api/baseball/*                   app/api/baseball/[...path], lib/api/proxy.ts
      → Python API ${BASEBALL_API_ORIGIN}/api/v1/*          baseball_api (pinned: openapi/)
  → fixture adapter (local development only)                lib/api/mock/ via `baseball-sample-data`
```

The data source is chosen once, in `lib/api/provider.tsx`. The real API is the default.
`NEXT_PUBLIC_BASEBALL_DATA_SOURCE=mock` selects fixtures outside production only, and
`next build` refuses it. Production builds alias the fixture module to a data-free stub, so no
fixture ships. Clients declare `capabilities`; the real API has `playerSeasonRanking: false`, so
the one-player view is hidden there. Contract status, field by field:
`docs/WEB_M2_SCHEMA_COMPATIBILITY.md`.

- Pages import only from `@/lib/api` (the types, the hook, `useBaseballClient`). No page or
  component imports a fixture.
- `BaseballClientProvider` (root layout) chooses the adapter once. Tests inject their own.
- `useBaseballQuery` re-runs only when the serialised question changes, aborts superseded
  requests, and exposes `retry`.
- Every adapter rejects with `BaseballApiError` and one of four kinds: `unavailable`,
  `invalid_request`, `unsupported` or `unknown`. `QueryErrorView` maps each kind to a state.

Client methods: `getCatalog()`, `searchPlayers(text)`, `getPlayer(id)`,
`getHistoricalExplorer(query)`, `getLeaderboard(query)`.

### TypeScript models

- **Wire types are generated, not written by hand.**
  `src/lib/api/generated/baseball-api.ts` comes from the pinned schema
  (`openapi/baseball-api.json`) via `npm run api:types`, and `npm run api:types:check` catches
  drift.
- **Only the HTTP adapter reads wire types.** Pages use the view models in
  `src/lib/api/types.ts` (`Catalog`, `MetricDefinition`, `PlayerSeason`, `QualificationInfo`,
  `Answer`, `HistoricalExplorerResult`, `LeaderboardResult`, …).
- **Missing fields stay empty.** Where the API doesn't provide a field yet, it is nullable or
  empty; it is never filled in by the frontend.

## 7. Sample data (fixtures)

Located in `src/lib/api/mock/fixtures/`. The rules:

- **Everything is declared, nothing is computed.** Rank order, totals, `qualified` flags and
  answer sentences are written out as data. The adapter only validates the request and looks up
  a canned answer.
- **An uncovered question is rejected as `unsupported`**, never answered with the nearest
  fixture. Coverage:
  - Historical Explorer: 2010–2025 and 2020–2025, all players, HR or OPS. Aaron Judge and
    Vladimir Guerrero Jr. by HR or OPS for 2010–2025.
  - Leaderboards: 2020–2025 by score, HR or OPS. 2010–2025 by HR.
- **Labelled everywhere.** The sidebar note (desktop) and header strip (phones) read "Sample data
  · numbers are illustrative, not official statistics". Player names are real so layouts are
  judged with real text; the numbers are approximations, not records.
- **Deliberate edge cases:** long and suffixed names ("Vladimir Guerrero Jr.", "Fernando Tatis
  Jr."), accents ("José Ramírez"), an apostrophe ("Ke'Bryan Hayes"), a missing SB, BB and
  position, a below-minimum season on a timeline, a span-minimum exclusion (Acuña) and a tie
  at .863.
- **Forcing states:** add `?mock=loading|slow|unavailable|empty` to any page URL.
- **Since WEB-M2,** fixtures are for local UI work and UI-behaviour tests only. Tests of what
  the pages show for real data use **recorded real API responses** (`src/test/recorded/`,
  recorded from the pinned API by `npm run api:record`) replayed through the real HTTP adapter.
  Live integration tests (`npm run test:live`) run against a running API.

## 8. Charts

There is no chart library. Recharts was evaluated, but it brings Redux Toolkit, Immer and
Reselect for what WEB-M1 needs, which is one line chart and ranking bars.

- `RankingBars`: a semantic `<ol>`. Names and values are real text that wraps on phones. Bar
  length is `value ÷ largest shown`, a display ratio rather than a statistic. The answer's row
  gets a full-strength bar, bold text and an "Answer" tag.
- `SeasonLineChart`: a responsive SVG (ResizeObserver) with a 2 px line, markers, gaps for
  missing seasons, hollow markers with a legend, hairline grid, a direct label on the answer
  season, a pointer crosshair tooltip and a "Show as table" alternative.
- `scale.ts`: nice ticks and linear mapping (geometry only).
- Colours: one series hue (dataviz reference slot 1) with a lighter step for context, selected
  separately for dark mode.
- Charts take display-ready props only, so swapping in a library later (if scatter, zoom or
  brushing are needed for Compare Players) touches only `components/charts/`.

## 9. Design primitives

`src/components/ui/primitives.tsx` (one stylesheet): `PageHeader`, `SectionHeader`, `Card`,
`AnswerCard`, `MetricTiles` (`<dl>`), `PlayerCard` + `RankBadge` + `Podium`, `Button`,
`ButtonLink` (primary / secondary / ghost), `ActionRow`, `Badge` (neutral / accent / good /
warn / dev), `ExploreMore` (native `<details>`), `LoadingState`, `ErrorState`, `EmptyState`.
Plus `DataSourceBadge`.

Tokens in `globals.css`: surfaces, ink, accent and status colours, chart colours, medals,
radius, spacing, type scale, gutter (16 / 24 / 40 px) and sidebar width. Each has light and
dark values. The palette continues the Streamlit U1 colours (navy ink, `#1f5fa8`).

## 10. Accessibility

- Semantic landmarks (aside, nav, main), a skip link, one `h1` per page and section headings.
- Every control is labelled. The year fields are a `fieldset` with a legend. The scope switch
  uses real radio buttons.
- Visible 3 px focus rings, and keyboard-only navigation works (verified in a browser).
- Rank, selection, trend and the answer row are never shown by colour alone: there's always
  printed text, an `aria-current`, a bar or a weight change, a tag or `aria-sort`.
- Tables have captions, row headers and a sticky player column, and sit in focusable,
  labelled scroll regions.
- `prefers-reduced-motion` is respected.
- axe-core 4.10 (WCAG 2.0/2.1 A + AA + best practice) found **0 violations** on Home, Historical
  Explorer (all players and one player) and Leaderboards (score and OPS) in light and dark mode.

## 11. What is real vs sample

The pages run on the real Python API by default (pinned `5ca7a26`). Sample fixtures exist for
local UI work only and never ship.

| From the real API | Formatted in TypeScript (display only) | Not on the web yet |
|---|---|---|
| Every number, name, rank, total and team | Rates `.311`, counts `1,234`, years `2022`, missing `—` | Hall of Fame Case Mode, relationship finder and scatterplot, several franchises at once, stat minimums you set yourself |
| The answer (headline, detail, context, tiles) | Tile values (looked up from the top row's stats) | Games or seasons per leaderboard player (the API doesn't compute it) |
| Qualification chip and explanation | Table columns drawn from the API's column list | Career Totals, Compare Players, Trend Value, Valuation (the API has no endpoints for them yet) |
| Catalog: stat lists, defaults, names, columns, filter options, weight and Top N bounds | | |
| Paging, filtering, one-player ranking, CSV file and its name | | |

## 12. Backend contracts

Served and used (API `5ca7a26`, `baseball_api` v1): `GET /catalog`, `/health`, `/players/search`,
`/players/{id}`, `/players/{id}/seasons` (not used by the pages), `/seasons` and `/leaderboards`
(each with `offset` / `limit`, filters, `format=csv`; `/seasons` also `player_id` and
`include_below_minimum`). The OpenAPI document is the only contract: wire types are generated into
`src/lib/api/generated/`, and only the HTTP adapter reads them.

Contracts still needed for the next pages (the schema describes these models but no endpoints
exist): Career Totals, Compare Players, Trend Value and Valuation; later, authenticated league
reads. Each needs the same shape as the served pages: the question as parameters, the answer
sentence and tile choice from the matching `u*_answers` function, qualification text, ranked rows
with table-column metadata, paging, and CSV where the Streamlit page has one.

## 13. Migration sequence

1. **Done (WEB-M1, WEB-M2):** foundation, Home, Historical Explorer and Leaderboards on the real
   Python API with catalog-driven tables, answers, filters, paging, one-player ranking and CSV.
2. **Next read-only pages** (each waits on API endpoints that don't exist yet): Career Totals,
   Compare Players, then Trend Value and Valuation. The API schema already describes
   `CareerSummary`, `ComparisonResult`, `TrendResult` and `ValuationResult`, and the Python
   functions are pure but still sit inside `streamlit_app.py` (see
   `docs/NEXTJS_API_CONTRACTS.md` on the API branch for the extraction plan).
3. Sleepers & Busts and ML Predictions (the ML model lifecycle needs a design first).
4. Auth (Supabase session in the shell), the account area and Pricing, then read-only My League
   views.
5. League mutations: lineup saves, waivers, trades, scoring-period finalisation.
6. Draft simulators; Ask AMI integration (owned by the AMI workstream).
7. Live Draft last: real-time state, timers and multiplayer.

## 14. Verification (WEB-M2 checkpoint, API 5ca7a26)

Run on a production build, through the proxy, against the real API over the Lahman data:

- `npm run check`: types drift check, typecheck, lint, 136 unit and page tests in 17 files, and
  the production build all pass. `npm run test:live`: 11 tests pass.
- **Parity with the existing Streamlit app** (its pages run headlessly with `AppTest` from the
  same commit): Historical Explorer (home runs, OPS) and Leaderboards (score, OPS) for the
  default ranges. The web app's headline, context, tiles, qualification chip and the first 25
  rows of each table equal the Streamlit pages: **1,700 cells compared, 0 mismatches**. The one
  textual difference is deliberate: Streamlit's score sentence ends with "Change the weights
  under Explore more.", which the API omits for other surfaces.
- **CSV:** the browser downloads the API's exact bytes (all 24,261 historical rows,
  1,957,269 bytes; a filtered export; the Leaderboards Top 25) under the API's filenames
  (`historical_explorer.csv`, `leaderboards.csv`). Each file's header equals the catalog's
  column labels. The proxy delivers it byte-for-byte.
- **Browser (Chromium) at 1280 / 430 / 390 / 360:** 21 flows pass and 28 page/width layouts have
  no horizontal overflow, no text under 11 px and no small tap targets. They cover navigation,
  direct URLs and refresh, Back/Forward across stat change and paging, filters, Top N, weights,
  the one-player view, all states (loading, empty, outage with Retry, a failing table page, a
  page past the end, a cold start with 503 + Retry-After, bad URL input), and the table
  scrolling inside its frame with the player column held. axe-core: 0 violations, light and
  dark, with Explore more open.
