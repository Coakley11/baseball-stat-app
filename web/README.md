# Baseball Explorer — web frontend

Next.js + React + TypeScript frontend for Baseball Explorer. It runs on its own; the Streamlit
app in the repository root is unaffected and keeps running as before.

The Python code stays authoritative for every statistic, ranking, rule and answer. This app
presents what the read-only Python API (`baseball_api`) returns, through a same-origin proxy.
Sample fixture data exists for local UI work only, is always labelled, and can't reach a
production build.

Docs:
- [`docs/NEXTJS_FRONTEND_FOUNDATION.md`](../docs/NEXTJS_FRONTEND_FOUNDATION.md): architecture.
- [`docs/WEB_M2_SCHEMA_COMPATIBILITY.md`](../docs/WEB_M2_SCHEMA_COMPATIBILITY.md): API contract
  status.

## Requirements

- Node.js ≥ 22.12 (developed on 22.23.3 LTS) with npm ≥ 11.
  npm 10.9 crashes resolving Vitest's optional peers (`Cannot read properties of null
  (reading 'edgesOut')`); `npm install -g npm@11` fixes it. `npm ci` from the lockfile is
  unaffected.
- For real data, a running Baseball API (Python). The pinned version is in
  `openapi/baseball-api.meta.json` (currently `a9a80f7` on `ui/u4-migration-readiness`).
  From a checkout or export of that commit:

  ```
  python -m uvicorn baseball_api.app:app --port 8601
  ```

  It loads the Lahman data for ~18 s after starting; the pages show their loading state until
  then.

## Configuration

| Variable | Where | Meaning |
|---|---|---|
| `BASEBALL_API_ORIGIN` | server (proxy) | Python API origin. Development defaults to `http://127.0.0.1:8601`; **required in production** (the proxy answers 503 without it) |
| `NEXT_PUBLIC_BASEBALL_DATA_SOURCE=mock` | local development only | Use sample fixtures instead of the API. `next build` refuses it, and production builds contain no fixtures |

## Commands

Run from this `web/` folder.

| Task | Command |
|---|---|
| Install dependencies | `npm ci` |
| Dev server (http://localhost:3000) | `npm run dev` |
| Production build | `npm run build` then `npm start` |
| Typecheck | `npm run typecheck` |
| Lint | `npm run lint` |
| Unit and component tests (recorded real API responses + UI behaviour) | `npm test` (watch mode: `npm run test:watch`) |
| Live integration tests against a running API | `BASEBALL_API_ORIGIN=http://127.0.0.1:8601 npm run test:live` |
| Generated API types up to date? | `npm run api:types:check` |
| Everything except live tests | `npm run check` |

Updating the API pin, with the new API running:

```
BASEBALL_API_COMMIT=<sha> npm run api:schema   # refresh openapi/baseball-api.json + meta
npm run api:types                              # regenerate src/lib/api/generated/baseball-api.ts
BASEBALL_API_COMMIT=<sha> npm run api:record   # re-record src/test/recorded/baseball-api.json
npm run typecheck && npm test && npm run test:live
```

Next.js collects anonymous telemetry by default; set `NEXT_TELEMETRY_DISABLED=1` to opt out.

## Sample mode (local development only)

With `NEXT_PUBLIC_BASEBALL_DATA_SOURCE=mock`, every page shows a "Sample data" notice. Adding
`?mock=` to any page URL forces a state:

| Value | Effect |
|---|---|
| `loading` | requests never finish (loading state) |
| `slow` | 2.5 s latency |
| `unavailable` | the data service is "down" (error state with Retry) |
| `empty` | the question matches nothing (empty state) |
