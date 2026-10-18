# Handoff: API additions requested by the Next.js frontend (WEB-M2)

**From:** the web workstream (`web/nextjs-foundation`).
**To:** the API workstream (`ui/u4-migration-readiness`, `baseball_api/`).
**Pinned against:** `a9a80f7` (WEB-PREP2).
**Context:** `docs/WEB_M2_DEPENDENCY_ASSESSMENT.md` on `web/nextjs-foundation`.

The web pages (Historical Explorer, Leaderboards) can already use most of `/seasons`,
`/leaderboards`, `/players/*` and `/openapi.json` as they are. Without the items below the
frontend would have to write wording or product settings itself, which the contract rules forbid.

All of these reuse functions the Streamlit pages already call; no new statistics are needed.
Shapes are proposals: name things your way, and the frontend regenerates types from
`/api/v1/openapi.json`.

Please keep changes additive within `v1`, and note the commit when each lands.

## Required before the web pages switch to real data

### R1. `GET /api/v1/catalog`
Product configuration the controls need, so the frontend never hard-codes it.

```
seasons: {first, last}
metrics: [{key, label, name, kind, decimals, higher_is_better}]           # one list, all pages
historical:   {metrics: [keys], defaults: {start, end, metric, order, split},
               filters: {bats: [{value, label}], positions: [...], position_sources: ["season","career"],
                         teams: [{value, label}],        # exactly the values `teams=` accepts
                         minimum_columns: [...]}}
leaderboards: {metrics: [keys], defaults: {start, end, metric, weights, limit},
               weight_stats: [...], weight_bounds: [0, 10], limit_bounds: [5, 100], minimum_columns: [...]}
```

- **Sources:** `services.SEASON_METRICS` / `LEADERBOARD_METRICS` / `WEIGHT_STATS` /
  `DEFAULT_WEIGHTS`, the default ranges in `season_leaders` / `leaderboard`, the page's
  Top-N bounds, `baseball_history` option builders.
- **Done when:**
  - defaults equal what the endpoints use when parameters are omitted;
  - each option list equals the Streamlit control's options.

### R2. Full Historical Explorer answer on `SeasonLeadersResult`
`answer: {headline, body, context, tile_metrics: ["HR","RBI","BA","OPS"]} | null`

- **Source:** `u1_answers.season_answer`, which `services.season_leaders` already calls. Today
  it keeps only `headline`; the others are `body`, `context` and `tiles` (send metric keys; the
  values are already in `rows[0].stats`).
- **Done when:** the strings equal what the Streamlit answer card shows for the same query,
  covered by a parity test like the existing ones.

### R3. Leaderboards answer on `LeaderboardResult`
`answer: {headline, body} | null`

- **Source:** `u1_answers.leaderboard_answer`.
- **Note:** its body ends with "Change the weights under Explore more.", which points at a
  Streamlit control. Please return wording that holds on any surface, either by dropping that
  sentence from the API copy or by returning it separately.
- **Done when:** the headline and body equal the Streamlit page; there's no UI-control
  wording.

### R4. Frontend-appropriate qualification copy on `Qualification`
- `summary`: the short chip line from `u1_answers.qualification_text`. Examples:
  - "Qualified hitters · at least 2,349 AB over 2020–2025"
  - "Qualified seasons · at least 437 AB in the season"
  - "Minimum you set · …"
  - "No at-bat minimum · part-time players can lead this list"
- `explanation`: optional plain text (no Markdown, no Streamlit control names).
- `text` can stay as it is for Streamlit parity.
- **Why:** `text` (from `rsq.qualification_caption`) contains `**…**` and "Change it under
  *Stat minimum filters*". The frontend won't parse Markdown or rewrite the meaning.
- **Note:** `qualification_text` reads session keys today, so it needs a pure variant that
  takes the resolved state `_qualification` already has.

### R5. Plain-language stat names
Add `name` to `MetricInfo` ("home runs", "batting average"), from `u1_answers.STAT_NAMES`
(including what `score` should read as). It's used in the controls and section titles.

## Needed for full parity (next)

### R6. Paging and complete data / export
- `offset` (0-based) on `/seasons` and `/leaderboards` (`total_rows` already exists; the
  200-row cap is fine).
- A full-result export with the same parameters, e.g. `format=csv`, matching the Streamlit
  CSV download's columns and rows.
- **Why:** the Streamlit Historical Explorer table shows every matching row and has a CSV
  download, and the web version must not lose that.

### R7. Player search speed
`/players/search` takes about 1.4 s for each new query (difflib over about 24,000 labels).
Please add the candidate prefilter your contracts doc proposes, applied to both surfaces so
matching stays identical.

- **Target:** a new query in under 300 ms warm.
- **Done when:** results equal today's for a fixed query set, or any intended differences are
  documented.

### R8. One-player view (if practical)
The web Historical Explorer has a "One player" mode that ranks one player's seasons. It's
hidden on real data until Python supports it.

- `player_id` on `/seasons`: the same pipeline, rows limited to that player; ranking,
  qualification and answer as usual.
- `include_below_minimum=true`: also return seasons below the active minimum, with
  `meets_minimum: false` and no rank, so a timeline can show them hollow. Without this, the
  frontend shows only qualified seasons.
- **Done when:** with `player_id`, the result equals the Historical Explorer rows filtered to
  that `playerID`.

## Optional

- `GET /players/{id}`: the summary only (today the frontend reads it from
  `/players/{id}/seasons`).
- While data is still loading, return `503 data_unavailable` with `Retry-After` instead of
  blocking on the load lock for about 18 s.

## What the frontend will not do

The frontend will not re-rank, re-filter, compute totals, rates, scores or qualification, write
answer sentences, or reinterpret a field. For any gap, it shows only what the API returns and
says plainly when something isn't available.

## Status (updated after the 5ca7a26 integration)

R1–R8 and both optional items are served at `5ca7a26` and adopted by the web app; the table-column
metadata the web asked for is in the catalog. Still open: games or seasons per leaderboard player
(decided: not added).

## Next contracts the web will need (nothing built on the web until these exist)

For each page the web needs the same shape the served pages have: the question as query
parameters, the answer (`headline`, `body`, `context`, tile choice) from the matching `u*_answers`
function, plain-text qualification where a rule applies, ranked rows with `columns` metadata,
paging, and CSV where the Streamlit page has an export.

1. **Career Totals:** `GET /players/{id}/career` or a ranked career list (the page ranks careers),
   from `u2_answers.career_answer`. Needs the career aggregation moved out of `streamlit_app.py`.
2. **Compare Players:** `GET` or read-only `POST /players/compare` (`player_ids[]`, range) returning
   per-metric values and who leads, from `u2_answers.comparison_answer`. Needs the comparison frame
   and the significance test extracted.
3. **Trend Value:** `GET /players/{id}/trends` and a ranked trend list, from `trend_slopes`. Needs
   `compute_player_trend_table` and `aggregate_recent_player_totals` moved out of the page.
4. **Valuation:** `GET /valuation` with the page's weights, from `valuation_scores`. Needs the
   hitter-only pool assembly extracted.

## Optional follow-up from the parity pass (not blocking)

**A summary line for a manual at-bat minimum on a counting-stat ranking.** For example
`/seasons?metric=HR&min_ab=500` filters correctly (`mode: "manual"`, `min_ab: 500`), but
`qualification.summary` is empty and `applies` is false, so a screen has nothing from Python to say
that a minimum is in force. Rate-stat rankings already get "Minimum you set · at least 300 AB in the
season". A matching short line for counting stats would let the web show it without writing its own
wording. The web shows nothing for it today.

Confirmed supported with no Python change: one player's career default (`player_id` without
`start` / `end`, each bound independently), `min_ab` / `min_{STAT}` on both ranking endpoints and the
CSV, and a `teams` list (a union).
