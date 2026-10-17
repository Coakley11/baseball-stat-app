import { proxyBaseballApi } from "@/lib/api/proxy";

/** Same-origin proxy to the Python Baseball API (see lib/api/proxy.ts). GET only. */
export async function GET(request: Request): Promise<Response> {
  return proxyBaseballApi(request);
}
