# WEB-M4A: security and operational hardening

Scope: the Next.js app in `web/` only. No change to the Python API, the generated contract
(`web/openapi`, still pinned at `5ca7a26`), calculations, or any Supabase / billing / auth / AMI /
Live Draft code.

## Security headers

Set for every route by `headers()` in `web/next.config.ts` (tests: `src/lib/security/headers.test.ts`).

| Header | Value |
|---|---|
| `Content-Security-Policy` | `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'` (`'unsafe-eval'` added to `script-src` by the development server only) |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `X-Frame-Options` | `DENY` (legacy twin of `frame-ancestors 'none'`) |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=(), usb=()` |
| `Cross-Origin-Opener-Policy` | `same-origin` |
| `Strict-Transport-Security` | `max-age=31536000`, production builds only |

**Why `'unsafe-inline'` for scripts.** Next.js emits inline bootstrap scripts. A nonce-based policy
would remove the need, but nonces require every page to render dynamically, and the Next.js
documentation states that Partial Prerendering is incompatible with nonce-based CSP. This app
uses `cacheComponents` and `partialPrefetching`, so the documented nonce-less policy is used and
everything else is kept closed. The browser only talks to its own origin (the Python API is
reached through the server-side proxy), so `connect-src` is `'self'`, with no external origins and
no wildcards. A stricter policy later would be either a nonce policy (accepting dynamic rendering)
or Next's experimental SRI hashes; both are a separate decision.

**HSTS.** Browsers ignore it over plain HTTP, so a local `next start` is unaffected. There is no
`includeSubDomains` or `preload`: those are commitments for the domain owner. For a production
build that is **not** served over HTTPS, build with `BASEBALL_WEB_HSTS=off`. Headers are fixed into
the build, so the variable is read at `next build`, not at `next start`.

### What `'unsafe-inline'` costs, and what still protects

`script-src 'self' 'unsafe-inline'` means the browser will run **any inline script or inline event
handler on the page**, so this CSP does **not** stop script injection by itself. If an attacker
could get markup into a page (reflected, stored or DOM-based XSS), an injected `<script>` or
`onerror=` handler would run. The built home page has 13 inline scripts (Next's bootstrap and
streaming data), so there is nothing to distinguish them from an injected one without a nonce or a
hash. `style-src 'unsafe-inline'` likewise permits injected CSS (and React's inline `style`).

What the policy **does** still do, for the same incident:

- Blocks script loaded from any other origin, `data:` scripts and `eval` (production), so an
  injection cannot pull in a second-stage payload or use string-to-code APIs.
- Blocks sending data out: `connect-src 'self'` stops `fetch`/XHR/WebSocket to other origins, and
  `form-action 'self'` stops forms posting elsewhere. `img-src` has no external origin either.
- Blocks plugins, `<base>` hijacking and framing (`object-src 'none'`, `base-uri 'self'`,
  `frame-ancestors 'none'`).

What actually keeps injection unlikely today, independent of CSP: React escapes everything it
renders; the app source has no `dangerouslySetInnerHTML`, `innerHTML`, `eval`, `new Function` or
`document.write`; the pages show only API data, and the browser never calls the API directly (a
GET-only, allowlisted, cookie-free proxy); and there are no cookies, sessions or secrets in this app
for a script to steal. This is why the trade-off is acceptable for a read-only analytics front end,
and why it must be revisited **before the web app gains sign-in, user-generated text, or any
rendered HTML from outside** (Shared Draft chat, league names, notes).

Ways to remove it, each its own decision:

1. **Nonce + `'strict-dynamic'`** through a Next.js `proxy.ts`. Strongest, but every page must
   render dynamically, which gives up Partial Prerendering and static caching.
2. **Subresource-Integrity hashes** (Next.js experimental): keeps static rendering, hash-based, but
   experimental and untested against this app.
3. Keep as is, and add a **Report-Only** policy of the strict form first to see what would break.

## Health and readiness

| Route | Meaning | Responses |
|---|---|---|
| `GET /api/health` (liveness) | The Next.js server is answering. Never touches Python, so an API outage cannot make an orchestrator restart a healthy web process | `200 {"status":"ok"}` |
| `GET /api/ready` (readiness) | The API answers `GET /api/v1/health` within 3 s **and** has loaded its data | `200 {"status":"ready"}`; `503 {"status":"warming"}` with `Retry-After: 5` (API up, still loading, `data_loaded: false`); `503 {"status":"unavailable"}` (timeout, connection error, non-200, unreadable or unexpected answer); `503 {"status":"not_configured"}` (no `BASEBALL_API_ORIGIN` in production) |

Both are `no-store` and call `connection()` so they run per request instead of being prerendered
at build time. The body is only a state word: no upstream URL, status, error text, build, season
list or environment value. Code: `src/lib/api/readiness.ts`, `src/app/api/health`, `src/app/api/ready`.

Note: the API's own `/health` answers 200 even while it loads (`data_loaded: false`), which is why
readiness reads that flag and reports `warming` rather than `ready`.

## Error handling

**Proxy logging** (`logProxyEvent` in `src/lib/api/proxy.ts`). One JSON line per failure on stderr
(`console.error`; `console.warn` for the API's normal loading answer):

```json
{"event":"baseball_proxy","route":"players.seasons","category":"timeout","status":502,"ms":30001}
```

- `route` is a fixed label from the allowlist (`catalog`, `seasons`, `leaderboards`, `players.search`,
  `players.detail`, `players.seasons`, `health`), never the request path.
- `category`: `timeout`, `network`, `not_configured`, `upstream_warming` (503 + Retry-After),
  `upstream_error` (other 5xx).
- Never logged: query strings, player ids or search text, headers, cookies, tokens, error messages
  (they can contain the internal API address). Not logged either: successes, the API's own 4xx
  answers, refused paths (attacker-controlled), and requests the browser abandoned (499).
- The proxy's responses and the API's error envelopes are unchanged.

**Error boundaries.** `src/app/error.tsx` (inside the app shell) and `src/app/global-error.tsx`
(root layout failures) show fixed generic text and a Try again button. The thrown error's message
is never rendered; `error.tsx` shows Next's `digest` as a reference to match against server logs.

## Cold start: reviewed, correct as built

The two limits do not conflict because they bound different things:

1. The API does **not** hold requests while it loads its data (about 18 s). Data routes answer
   `503 data_unavailable` with `Retry-After: 5` immediately (`svc.STORE.get(wait=False)`).
2. The proxy forwards that status and `Retry-After` untouched (and logs it as `upstream_warming`).
3. The client waits as told and retries the catalog for up to 60 s across attempts. Both data
   calls (`getHistoricalExplorer`, `getLeaderboard`) wait for the catalog first, so the whole page
   waits on this loop and shows its loading state.
4. The proxy's 30 s is per upstream request and only matters when the API hangs. That becomes
   `502 upstream_unavailable` with no `Retry-After`; the client shows "unavailable" at once,
   makes no blind retry, and does not remember the failure (the next call tries again).
5. A 503 without `Retry-After` (data missing, or `upstream_not_configured`) and a 500 are not
   retried.

No defect was found, so no behavior was changed. Three observations, deliberately left alone:

- The window is checked before each wait, so the worst case is about 60 s plus one more wait and
  one more request (the API's wait is 5 s). It is a soft cap, as documented ("up to a minute").
- The client trusts the `Retry-After` value. The API sends 5; a hypothetical very large value from
  a different upstream would be waited out in full. It is not worth code while the API is the only
  upstream, but is the first thing to clamp if a gateway that sets `Retry-After` is ever put in front.
- `players/search` and `players/{id}` do not wait on the catalog, so during the first seconds of a
  cold start the player picker can show "unavailable" for a moment. Unchanged from WEB-M2.

Tests: `src/lib/api/coldStart.test.ts` runs the real proxy and the real client together against a
fake API with virtual time (warming then answer; the 60 s window closing; a hung API; 503 without
Retry-After; 500; not configured; a gateway 504 with Retry-After; the 30 s bound).
