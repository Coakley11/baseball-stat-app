# WEB-M2 validation report

Status: WEB-M2 is frozen. This report records what was verified, against which commits, and how to repeat it.

## Exact commits

| Item | Commit |
|---|---|
| Frontend (`web/nextjs-foundation`) | `c97865226ff52a7c90feca753811313059f6d2d5` |
| API contract (`api/web-m2-contracts`), pinned in `web/openapi/baseball-api.meta.json` | `5ca7a26b2c57f5835a931011fa79700487aa4a82` |

The API was run from a `git archive` export of `5ca7a26`. The API worktree and branch were not modified.
Test counts apply to the frontend commit above; later changes will change them.

## Results

| Check | Result | Artifact (`docs/validation/web-m2/`) |
|---|---|---|
| `npm run check` (types-drift check, typecheck, lint, unit tests, production build) | exit 0 | `npm_run_check_final.txt` |
| Unit and page tests, using recorded real API responses | 167 tests in 18 files | `unit_test_inventory.txt` |
| Live API tests | 18 (11 + 7) pass against the running API; skipped when no API origin is set | `live_test_inventory.txt` |
| Browser workflows (Chromium; production build, proxy, real API) | 27 of 27 pass at 1280, 430, 390 and 360 px | `m2acc2.json` |
| Layout at 28 page/width combinations | no horizontal overflow, no text under 11 px, no small tap targets | `m2acc2.json` |
| axe-core (WCAG 2 A/AA and best practice) | 0 violations in 6 runs (light and dark, Explore more open) | `m2acc2.json` |
| Streamlit parity | 1,700 table cells compared, 0 mismatches (4 cases x 25 rows) | `parity_result.json`, `streamlit_dump.json` |
| CSV | browser downloads are byte-identical to the API's files, under the API's filenames | `m2acc2.json` (`misc`) |
| Production build contains no sample data | 0 fixture strings in `.next`, source maps included | session check |

### Parity method
`scripts/stream_dump.py` runs the existing Streamlit pages headlessly (`AppTest`) from the `5ca7a26` export
for Historical Explorer (home runs, OPS) and Leaderboards (score, OPS) at their default ranges. It writes the
answer card, chips, the range and sort used, and the first 25 rows. `scripts/parity.py` renders the same four
questions in a browser and compares headline, detail sentence, context, tiles, qualification chip, column
headers and every cell. Numbers are compared as numbers (tolerance 0.0005). The one text difference is
deliberate: Streamlit's score sentence ends with "Change the weights under Explore more.", which the API omits
for other screens.

## How to reproduce

1. Export the API commit and start it (from a checkout of the API branch; do not touch that worktree):
   ```
   git archive 5ca7a26 | tar -x -C <empty export dir>
   cd <export dir> && python -m uvicorn baseball_api.app:app --port 8601
   ```
2. Static checks and unit tests (from `web/`): `npm run check`
3. Live tests (from `web/`): `BASEBALL_API_ORIGIN=http://127.0.0.1:8601 npm run test:live`
4. Production build and server (from `web/`):
   `npm run build && BASEBALL_API_ORIGIN=http://127.0.0.1:8601 npm start -- -p 3100`
5. Browser flows and parity (scripts in `docs/validation/web-m2/scripts/`):
   ```
   python -I scripts/m2_acceptance.py http://localhost:3100 http://127.0.0.1:8601 <out dir>
   PYTHONPATH=. python stream_dump.py <out>/streamlit_dump.json      # run from the export dir
   python -I scripts/parity.py http://localhost:3100 <out>/streamlit_dump.json <out dir>
   ```
   `scripts/probe_contract.py` is the read-only probe used to confirm the API's career, minimum and
   multi-franchise behaviour. `scripts/mobilebar.py` is the phone question-bar check.

Tooling: Node 22.23.3 and npm 11.21 (npm 10 crashes resolving Vitest peers), Playwright with Chromium, Python 3.

## Known limitations and outstanding parity gaps

- Hall of Fame Case Mode, the relationship finder and scatterplot are not built.
- Tables show 25 rows per page; Streamlit shows more at once.
- Leaderboard cards have no games or seasons count (the API provides none; accepted).
- On counting-stat rankings with a manual at-bat minimum, the API returns no `summary`, so no qualification
  chip shows. The filter itself is correct. Optional request to the API workstream (see `WEB_M2_API_HANDOFF.md`).
- The score sentence differs from Streamlit by one deliberate sentence (above).
- axe-core is loaded from a CDN, so the accessibility run needs network access.
- TypeScript 6 is paired with `openapi-typescript` 7.13.0 through a scoped npm override
  (see `WEB_M2_SCHEMA_COMPATIBILITY.md`).
- Not covered: Career Totals, Compare Players, Trend Value, Valuation (WEB-M3 and later).

## Evidence kept outside the repository

The complete original bundle, including all browser screenshots, is kept at
`C:\Users\danie\Documents\baseball-web-evidence\web-m2-validation\`. The repository holds only the small
text artifacts and scripts listed above.
