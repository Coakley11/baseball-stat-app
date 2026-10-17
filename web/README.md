# Baseball Explorer — web frontend

Next.js + React + TypeScript frontend for Baseball Explorer. It runs on its own; the Streamlit
app in the repository root is unaffected and keeps running as before.

The Python code stays authoritative for every statistic, ranking and rule. This app presents
what the Python API returns. Until that API exists, pages read **sample fixture data** through
the same client interface (shown everywhere with a "Sample data" badge).

Architecture, routes and the migration plan: [`docs/NEXTJS_FRONTEND_FOUNDATION.md`](../docs/NEXTJS_FRONTEND_FOUNDATION.md).

## Requirements

- Node.js ≥ 22.12 (developed on 22.23.3 LTS) with npm ≥ 11.
  npm 10.9 crashes resolving Vitest's optional peers (`Cannot read properties of null
  (reading 'edgesOut')`); `npm install -g npm@11` fixes it. `npm ci` from the lockfile is
  unaffected.

## Commands

Run from this `web/` folder.

| Task | Command |
|---|---|
| Install dependencies | `npm ci` |
| Dev server (http://localhost:3000) | `npm run dev` |
| Production build | `npm run build` then `npm start` |
| Typecheck | `npm run typecheck` |
| Lint | `npm run lint` |
| Unit/component tests | `npm test` (watch mode: `npm run test:watch`) |
| Everything above | `npm run check` |

Next.js collects anonymous telemetry by default; set `NEXT_TELEMETRY_DISABLED=1` to opt out.

## Forcing page states (development)

Fixture mode honours `?mock=` on any page URL:

| Value | Effect |
|---|---|
| `loading` | requests never finish (loading state) |
| `slow` | 2.5 s latency |
| `unavailable` | the data service is "down" (error state with Retry) |
| `empty` | the question matches nothing (empty state) |
