import { connection } from "next/server";

import { READINESS_RETRY_AFTER_S, checkReadiness } from "@/lib/api/readiness";

/**
 * Readiness: this web app can serve data, meaning the Python API answers its health probe within a
 * short bound and has loaded its data. 200 `ready`; otherwise 503 with only a state word (never
 * the upstream URL, status, error text or build). While the API is still loading its data the 503
 * carries Retry-After, the same signal the API itself uses on a cold start.
 */
export async function GET(): Promise<Response> {
  await connection();
  const state = await checkReadiness();
  if (state === "ready") {
    return Response.json({ status: "ready" }, { headers: { "cache-control": "no-store" } });
  }
  const headers: Record<string, string> = { "cache-control": "no-store" };
  if (state === "warming") headers["retry-after"] = String(READINESS_RETRY_AFTER_S);
  return Response.json({ status: state }, { status: 503, headers });
}
