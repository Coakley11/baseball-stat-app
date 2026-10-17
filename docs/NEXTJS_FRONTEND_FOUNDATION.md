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

**Historical Explorer** (`?from&to&metric&order&player&scope=player`):

- Controls: Seasons (from/to, committed on blur or Enter), Rank by, and Whose seasons
  (All players / One player with player search).
- Answer: the API headline and detail, a context kicker ("2024 · NYY · CF") and 3–4 key-metric
  tiles. Tiles sit two per row on phones and never shrink below about 140 px.
- Qualification chip for rate stats ("Qualified seasons · at least 437 AB in the season").
- Default visual: top-10 seasons as ranking bars (all players), or one player's season line,
  with below-minimum seasons drawn hollow.
- Next steps: "All of {player}'s seasons" or "Best seasons by every player", plus "Leaders over
  {range}".
- Explore more: Order (moved here as in U1), every returned season in a scrollable table with
  the ranked column marked (`aria-sort`, arrow, tint), and a note listing the Streamlit filters
  still to come.

**Leaderboards** (`?from&to&metric`):

- Answer kicker "Ranked by {stat} · {range}", the API headline and detail, the qualification
  chip ("Qualified hitters · at least 2,349 AB over 2020–2025") and "N qualified hitters ranked".
- Top 3 as player cards with printed rank badges (the medal colour is decoration only).
- Top-10 ranking bars.
- Next steps: "{Leader}'s best seasons", "Best single seasons, {range}".
- Explore more: the full ranking table, the score definition (API text), and a note on weights,
  minimums, Top-N and export still to come.

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
  → fixture adapter (today)                                 lib/api/mock/mockClient.ts
  → HTTP adapter (next)                                     not written: contracts pending
```

- Pages import only from `@/lib/api` (the types, the hook, `useBaseballClient`). No page or
  component imports a fixture.
- `BaseballClientProvider` (root layout) chooses the adapter once. Tests inject their own.
- `useBaseballQuery` re-runs only when the serialised question changes, aborts superseded
  requests, and exposes `retry`.
- Every adapter rejects with `BaseballApiError` and one of four kinds: `unavailable`,
  `invalid_request`, `unsupported` or `unknown`. `QueryErrorView` maps each kind to a state.

Client methods: `getCatalog()`, `searchPlayers(text)`, `getPlayer(id)`,
`getHistoricalExplorer(query)`, `getLeaderboard(query)`.

### TypeScript models (temporary)

`src/lib/api/types.ts` holds hand-written models designed around a clean JSON contract, not
Streamlit's DataFrames: `Catalog`, `MetricDefinition`, `YearRange`, `PlayerSummary`,
`PlayerSeason`, `StatLine`, `QualificationInfo`, `Answer`, `HistoricalExplorerQuery/Result`,
`SeasonChart`, `LeaderboardQuery/Result/Entry`, `ScoreDefinition`. **Replace this file with
types generated from the Python OpenAPI schema** (or re-export them from it) when that schema
exists. Pages will then show compile errors only where the shape really changed.

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
- When the API arrives, the HTTP adapter replaces this one. The fixtures stay for tests only.

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

| Real now | Sample (fixtures) |
|---|---|
| Shell, navigation, routing, URL state, Back/Forward | Every number, name list, rank and sentence |
| All loading / empty / error states and their triggers | Catalog (metrics, defaults, year bounds): mirrors `streamlit_app.py` |
| Formatting (`.311`, `1,234`, `—` for missing) | Player search results |
| Accessibility, responsive layout, dark mode | Qualification text and flags |

## 12. Backend contracts needed

Proposed to the API workstream. These are shapes the pages need, not a demand for exact names.

1. **`GET catalog`**: year bounds, metric definitions (`key`, `label`, plain `name`, `format`:
   rate / count / score), and per-page metric lists and defaults.
2. **`GET players?search=`** and **`GET players/{id}`**: `PlayerSummary` (id = Lahman `playerID`).
3. **`GET historical-explorer?from&to&metric&order&player`**, returning `HistoricalExplorerResult`:
   - the normalised query
   - `answer` {headline, detail, context}, built by `u1_answers.season_answer` and written for
     any surface (no "under Explore more" wording)
   - `qualification` {kind, summary, minAtBats, scope}
   - `topSeasonId`, `keyMetrics`, `columns`
   - ranked `seasons` (first page) + `totalCount`
   - per-season `qualified`
   - `chart` {kind: ranking | timeline, title, seasonIds}
4. **`GET leaderboards?from&to&metric`** (custom weights later), returning `LeaderboardResult`:
   - `answer` (`u1_answers.leaderboard_answer`)
   - `qualification`, ranked `entries` {rank, player, seasons, stats}, `totalRanked`, `columns`
   - `score` {summary, weights}
5. **Errors**: a JSON body with a machine-readable code that maps to `unavailable`,
   `invalid_request` or `unsupported`, plus a user-facing message.
6. **Pagination** (offset/limit or cursor) for full tables, and later filter parameters (bats,
   position mode, franchise/league, split seasons, stat minimums, HoF case mode) and CSV export.
7. **CORS or a same-origin proxy**: to decide when the HTTP adapter is written.

## 13. Migration sequence (proposed)

1. **WEB-M1 (this):** foundation, Home, Historical Explorer, Leaderboards on sample data.
2. **WEB-M2:** connect the HTTP adapter to the read-only Python API for the M1 pages; generate
   types from OpenAPI; add the Explore more filters, pagination and export; add redirects
   from Streamlit `?active_page=` keys; add Career Totals.
3. Compare Players and the Insights pages (Trend Value, Valuation, ML, Sleepers & Busts):
   read-only, chart-heavier.
4. Auth (Supabase session in the shell), account area and Pricing, then read-only My League
   views (Standings, Waiver Wire reads).
5. League mutations: lineup saves, waivers, trades, scoring-period finalisation (needs write APIs
   with the existing ownership and lock checks).
6. Draft Room / Assistant / Lab simulators; Ask AMI integration (owned by the AMI workstream).
7. Live Draft last: real-time state, timers and multiplayer.

## 14. Verification (WEB-M1 checkpoint)

- `npm run typecheck`, `npm run lint`, `npm test` (60 tests in 9 files) and `npm run build`
  all pass. All four routes prerender as static shells; answers load client-side.
- Browser acceptance (Chromium via Playwright, production build) at 1280 / 430 / 390 / 360:
  - no horizontal overflow
  - no visible text under 11 px, no tap target under 24 px
  - keyboard skip link and sidebar navigation work
  - phone menu: open, Esc, focus return, navigate-and-close
  - stat change and Back, the player picker and timeline, and the cross-page links work
  - all forced states render
  - axe: 0 violations, light and dark
