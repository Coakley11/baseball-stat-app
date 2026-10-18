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
 * - 30 s timeout: the API loads its data for ~18 s after a cold start, and requests wait on it.
 */

export const PROXY_PREFIX = "/api/baseball/";
const TIMEOUT_MS = 30_000;
const ALLOWED_PATHS = [
  /^health$/,
  /^catalog$/,
  /^players\/search$/,
  // A Lahman player id, but not the `search` / `resolve` routes (resolve isn't exposed).
  /^players\/(?!search$|resolve$)[A-Za-z0-9._-]{1,32}$/,
  /^players\/[A-Za-z0-9._-]{1,32}\/seasons$/,
  /^seasons$/,
  /^leaderboards$/,
];
// content-disposition names CSV downloads; retry-after is the API's "still loading" hint.
const PASSED_HEADERS = ["content-type", "content-disposition", "cache-control", "server-timing", "retry-after"];

/** BASEBALL_API_ORIGIN, or the local API in development. `null` in production without one. */
export function baseballApiOrigin(env: Record<string, string | undefined> = process.env): string | null {
  const configured = env.BASEBALL_API_ORIGIN?.trim();
  if (configured) return configured.replace(/\/+$/, "");
  return env.NODE_ENV === "production" ? null : "http://127.0.0.1:8601";
}

function proxyError(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message } }, { status, headers: { "cache-control": "no-store" } });
}

export async function proxyBaseballApi(
  request: Request,
  { origin = baseballApiOrigin(), fetchImpl = fetch }: { origin?: string | null; fetchImpl?: typeof fetch } = {},
): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname.startsWith(PROXY_PREFIX) ? url.pathname.slice(PROXY_PREFIX.length) : "";
  if (!ALLOWED_PATHS.some((pattern) => pattern.test(path))) {
    return proxyError(404, "not_found", "No such endpoint.");
  }
  if (!origin) {
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
  } catch {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    return proxyError(502, "upstream_unavailable", "The baseball data service didn't respond.");
  }

  const headers = new Headers();
  for (const name of PASSED_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers });
}
