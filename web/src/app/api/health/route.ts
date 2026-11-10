import { connection } from "next/server";

/**
 * Liveness: the Next.js server is up and answering. It deliberately does not touch the Python
 * API, so an API outage never makes an orchestrator restart a healthy web process (use
 * /api/ready for that). `connection()` keeps the response per-request instead of a build-time
 * prerender.
 */
export async function GET(): Promise<Response> {
  await connection();
  return Response.json({ status: "ok" }, { headers: { "cache-control": "no-store" } });
}
