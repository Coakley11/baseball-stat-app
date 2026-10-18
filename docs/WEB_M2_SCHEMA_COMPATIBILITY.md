# WEB-M2: frontend contracts vs the real API schema

**Backend contract in use:** `baseball_api` @ **`5ca7a26`** (`api/web-m2-contracts`, accepted).
Earlier slices were pinned to `a9a80f7`; that history is at the end.

**Schema:** `web/openapi/baseball-api.json` (OpenAPI 3.1.0, 8 paths, 39 schemas), with
`openapi/baseball-api.meta.json` recording the commit. It is identical to the document built
offline from that commit.

**Types:** `web/src/lib/api/generated/baseball-api.ts`, produced by `npm run api:types`
(openapi-typescript 7.13.0, `--immutable`, never hand-edited). `npm run api:types:check` fails on
drift and runs first in `npm run check`. `.gitattributes` keeps both files LF so the check works
on Windows.

**Layering:**

```
page / component
  → useBaseballQuery → BaseballClient (typed interface)     lib/api/client.ts
  → HTTP adapter: request building, error mapping, catalog   lib/api/http/httpClient.ts
  → mapping: generated wire types → view models              lib/api/http/mapping.ts
  → /api/baseball/* proxy → Python API
```

Pages never see generated types, `fetch`, or wire field names. The adapter is the one place for
response normalization, error mapping, the cold-start wait and (later) authentication.

## How each contract item is used now

| Item | API field | Frontend |
|---|---|---|
| Catalog (R1) | `GET /catalog` | Fetched once per client. Years, stat lists, defaults, labels, plain names, table columns, filter options, weight and Top N bounds all come from it. The interim catalog is deleted |
| Cold start | `503 data_unavailable` + `Retry-After` | The adapter waits as told (up to a minute) before answering; the page shows its loading state, not an error. The proxy forwards `retry-after` |
| Historical answer (R2) | `answer {headline, body, context, tile_metrics}` | Headline, detail, kicker and tiles. Tile values are looked up from `rows[0].stats` |
| Leaderboards answer (R3) | `answer {headline, body, context}` | Headline, detail and kicker |
| Qualification (R4) | `qualification.summary`, `.explanation` | The chip shows `summary`; Explore more shows `explanation`. `text` (Markdown, names a Streamlit control) is never used |
| Stat names (R5) | `MetricInfo.name` | Controls, titles and captions |
| Paging (R6) | `offset`, `total_rows`, `ranked_rows` | Previous / Next over 25-row pages |
| CSV (R6) | `format=csv` + `Content-Disposition` | A download link through the proxy; no file is built in the browser |
| One player (R8) | `player_id`, `include_below_minimum`, `meets_minimum`, `rank: null` | The one-player view is on. Below-minimum seasons are drawn hollow and noted in the table. It uses the page's year range (the API's career default isn't used) |
| Table columns | `catalog.*.columns [{label, field, metric}]` | `ResultTableView` renders exactly these, in this order, with `field` paths looked up in each row |
| Filters | `bats`, `positions`, `position_source`, `teams`, `combine` | Explore more on Historical Explorer; the options are the catalog's |
| Top N, weights | `limit`, `weights` | Explore more on Leaderboards |
| Search (R7) | `/players/search` | Debounced picker; 150–300 ms per new query in testing |

## Differences that remain (by design or by contract)

| # | Difference | Handling |
|---|---|---|
| 1 | Field names are snake_case | The mapping layer renames them; meanings are unchanged |
| 2 | No games or seasons total on leaderboard rows (`stats.G` is null) | Decided: no new statistic. Cards show the player's at-bats (an authoritative field) instead |
| 3 | `SeasonLeadersResult.headline` is kept for v1 compatibility | Not used; the frontend reads `answer.headline` |
| 4 | `/seasons` also accepts the `yearID` metric; the Streamlit page doesn't offer it | Not offered (it isn't in `historical.metrics`) |
| 5 | `/health.build` reports the tree's deploy marker, not the running commit | The pinned commit is recorded in `openapi/baseball-api.meta.json` |
| 6 | Franchise / league filter accepts several values; the web control takes one | A gap against Streamlit's multiselect. The URL already holds a list |
| 7 | Stat minimums you set yourself (`min_ab`, `min_HR`, …) | Not on the web yet; the API supports them |
| 8 | `min_{STAT}` is one literal query parameter in OpenAPI | Documented placeholder; not used by the frontend |
| 9 | `/players/resolve` and `/players/{id}/seasons` | Not used by the pages. The proxy allows `/players/{id}/seasons` but not `resolve` (a test guards this) |

## Verification at 5ca7a26

The API was exported with `git archive` into a temporary directory and run there (no worktree or
branch was touched). Results are in `docs/NEXTJS_FRONTEND_FOUNDATION.md` §14: types drift check and
typecheck clean, 136 unit tests, 11 live tests, 21 browser flows at four widths, axe 0 violations,
and 1,700 table cells compared with the existing Streamlit pages with no mismatches.

## Dependency note: TypeScript 6 and openapi-typescript

`openapi-typescript` 7.13.0 declares a peer of `typescript ^5`; WEB uses TypeScript 6.0.3 (7 isn't
usable yet because typescript-eslint supports < 6.1). A scoped npm override in `web/package.json`,

```json
"overrides": { "openapi-typescript": { "typescript": "$typescript" } }
```

makes only that tool use the repo's TypeScript. Generation works and the output compiles for the
`a9a80f7` and `5ca7a26` schemas. Review when `openapi-typescript` declares TypeScript 6 support
(remove the override) or when moving to TypeScript 7.

## History

- **`a9a80f7`** (WEB-M2B to M2E): 6 paths. No catalog, answers were headline only, qualification
  was a Markdown caption, no paging or CSV, no one-player ranking. The frontend used an interim
  catalog, number-only qualification chips and a data-free Leaderboards title. All of that is
  removed.
- **`5ca7a26`** adds the catalog and its table columns, the full answers, plain-text
  qualification, paging, CSV, one-player ranking, `/players/{id}` and a fast player search.
