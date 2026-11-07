/**
 * Readiness: can this web app reach the Python Baseball API *and* has the API loaded its data?
 *
 * Probes `${origin}/api/v1/health` once, with a short bound, and reduces the outcome to four
 * states. Nothing from the upstream is passed on: not its URL, status text, error text, build
 * or season list. The caller (the /api/ready route) shows only the state.
 *
 *   ready           API answered 200 `status: "ok"` and `data_loaded: true`
 *   warming         API answered but is still reading its data (cold start); retry shortly
 *   unavailable     no answer in time, a connection error, a non-200, or an unreadable answer
 *   not_configured  no API origin is configured (production without BASEBALL_API_ORIGIN)
 */
import { baseballApiOrigin } from "./proxy";

export type ReadinessState = "ready" | "warming" | "unavailable" | "not_configured";

/** Short on purpose: a load balancer or orchestrator probe must not hang behind a stuck API. */
export const READINESS_TIMEOUT_MS = 3_000;

/** Seconds a client should wait before probing again while the API is warming up. */
export const READINESS_RETRY_AFTER_S = 5;

export async function checkReadiness({
  origin = baseballApiOrigin(),
  fetchImpl = fetch,
  timeoutMs = READINESS_TIMEOUT_MS,
}: { origin?: string | null; fetchImpl?: typeof fetch; timeoutMs?: number } = {}): Promise<ReadinessState> {
  if (!origin) return "not_configured";
  try {
    const res = await fetchImpl(`${origin}/api/v1/health`, {
      method: "GET",
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(timeoutMs),
      cache: "no-store",
    });
    if (res.status !== 200) return "unavailable";
    const body = (await res.json()) as { status?: unknown; data_loaded?: unknown } | null;
    if (body?.status !== "ok") return "unavailable";
    return body.data_loaded === true ? "ready" : "warming";
  } catch {
    // Timeout, refused connection, DNS failure, or a body that isn't JSON.
    return "unavailable";
  }
}
