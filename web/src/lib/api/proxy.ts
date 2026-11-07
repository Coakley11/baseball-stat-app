/**
 * Server-side, same-origin proxy to the read-only Python Baseball API.
 *
 * Browser → /api/baseball/<path>?<query> (this app) → ${BASEBALL_API_ORIGIN}/api/v1/<path>?<query>.
 *
 * - Only the endpoints the web pages use are forwarded (allowlist), GET only (the route exports
 *   only GET).
 * - No cookies, auth headers or client headers are forwarded; only safe response headers come
 *   back.
 * - API responses, including its own error envelopes, pass through untouched. The proxy adds
 *   two codes of its own: `upstream_unavailable` (502: the API didn't answer) and
 *   `upstream_not_configured` (503: no origin set in production).
 * - 30 s timeout per request. During the API's ~18 s cold start data routes do not wait: the API
 *   answers 503 + Retry-After at once and this proxy passes both through, so the browser client
 *   (lib/api/http/httpClient.ts) does the waiting, for up to 60 s across attempts. The 30 s bound
 *   only guards a hung API: that becomes a 502 `upstream_unavailable` (no Retry-After), which the
 *   client reports as "unavailable" instead of retrying blindly.
 * - Failures are logged server-side as one JSON line each (see `logProxyEvent`): a route label, a
 *   category, the status and the elapsed time, and nothing the user typed.
 */

export const PROXY_PREFIX = "/api/baseball/";
const TIMEOUT_MS = 30_000;
// `route` is the only name that reaches the logs: it is fixed here, so a player id or search text
// from the request can never end up in them.
const ALLOWED_PATHS: { route: string; pattern: RegExp }[] = [
  { route: "health", pattern: /^health$/ },
  { route: "catalog", pattern: /^catalog$/ },
  { route: "players.search", pattern: /^players\/search$/ },
  // A Lahman player id, but not the `search` / `resolve` routes (resolve isn't exposed).
  { route: "players.detail", pattern: /^players\/(?!search$|resolve$)[A-Za-z0-9._-]{1,32}$/ },
  { route: "players.seasons", pattern: /^players\/[A-Za-z0-9._-]{1,32}\/seasons$/ },
  { route: "seasons", pattern: /^seasons$/ },
  { route: "leaderboards", pattern: /^leaderboards$/ },
];
// content-disposition names CSV downloads; retry-after is the API's "still loading" hint.
const PASSED_HEADERS = ["content-type", "content-disposition", "cache-control", "server-timing", "retry-after"];

/** BASEBALL_API_ORIGIN, or the local API in development. `null` in production without one. */
export function baseballApiOrigin(env: Record<string, string | undefined> = process.env): string | null {
  const configured = env.BASEBALL_API_ORIGIN?.trim();
  if (configured) return configured.replace(/\/+$/, "");
  return env.NODE_ENV === "production" ? null : "http://127.0.0.1:8601";
}

export type ProxyEventCategory = "timeout" | "network" | "not_configured" | "upstream_warming" | "upstream_error";

export interface ProxyEvent {
  route: string;
  category: ProxyEventCategory;
  /** The status this proxy returned (the API's own, or 502 / 503 for the proxy's errors). */
  status: number;
  ms: number;
}

/**
 * One JSON line per failure, to stderr. Only the fixed route label, a category, the status and the
 * duration: never the URL, query string, headers, cookies, player ids or search text, and never an
 * error's message (it can carry the internal API address).
 */
export function logProxyEvent(event: ProxyEvent): void {
  const line = JSON.stringify({ event: "baseball_proxy", ...event });
  if (event.category === "upstream_warming") console.warn(line);
  else console.error(line);
}

function proxyError(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message } }, { status, headers: { "cache-control": "no-store" } });
}

export async function proxyBaseballApi(
  request: Request,
  {
    origin = baseballApiOrigin(),
    fetchImpl = fetch,
    log = logProxyEvent,
  }: { origin?: string | null; fetchImpl?: typeof fetch; log?: (event: ProxyEvent) => void } = {},
): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname.startsWith(PROXY_PREFIX) ? url.pathname.slice(PROXY_PREFIX.length) : "";
  const allowed = ALLOWED_PATHS.find(({ pattern }) => pattern.test(path));
  if (!allowed) {
    return proxyError(404, "not_found", "No such endpoint.");
  }
  const { route } = allowed;
  const started = Date.now();
  const report = (category: ProxyEventCategory, status: number) => log({ route, category, status, ms: Date.now() - started });
  if (!origin) {
    report("not_configured", 503);
    return proxyError(503, "upstream_not_configured", "The baseball data service isn't configured.");
  }

  let upstream: Response;
  try {
    upstream = await fetchImpl(`${origin}/api/v1/${path}${url.search}`, {
      method: "GET",
      headers: { accept: "application/json" },
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(TIMEOUT_MS)]),
      cache: "no-store",
    });
  } catch (error) {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    report(error instanceof Error && error.name === "TimeoutError" ? "timeout" : "network", 502);
    return proxyError(502, "upstream_unavailable", "The baseball data service didn't respond.");
  }
  if (upstream.status >= 500) {
    // 503 + Retry-After is the API's normal "still loading its data" answer, not a fault.
    report(upstream.status === 503 && upstream.headers.has("retry-after") ? "upstream_warming" : "upstream_error", upstream.status);
  }

  const headers = new Headers();
  for (const name of PASSED_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers });
}
