/**
 * Replays real Baseball API responses (src/test/recorded/baseball-api.json, recorded from the
 * pinned API over the real Lahman data by scripts/record-api-responses.mjs) through the real
 * HTTP adapter. Tests exercise the production mapping code against genuine data, with no
 * network.
 */
import { vi } from "vitest";

import type { BaseballClient } from "@/lib/api";
import { createHttpClient } from "@/lib/api/http/httpClient";

import recordedFile from "./recorded/baseball-api.json";

interface Recording {
  status: number;
  body: unknown;
}

export const RECORDED = recordedFile as { api_commit: string; recorded_at: string; responses: Record<string, Recording> };
const BASE = "http://recorded.test/api/v1";

export function recorded<T = Record<string, unknown>>(request: string): T {
  const hit = RECORDED.responses[request];
  if (!hit) throw new Error(`No recording for "${request}"`);
  return hit.body as T;
}

export interface RecordedClientOptions {
  /** Serve one recording in place of another: { "<request sent>": "<recording to return>" }. */
  substitute?: Record<string, string>;
  /** Make the transport fail ("network") or return a status without calling the recording. */
  fail?: "network" | number | (() => "network" | number | null);
}

export function createRecordedClient(options: RecordedClientOptions = {}): { client: BaseballClient; fetchImpl: ReturnType<typeof vi.fn<typeof fetch>> } {
  const fetchImpl = vi.fn<typeof fetch>(async (input, init) => {
    if (init?.signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const failure = typeof options.fail === "function" ? options.fail() : options.fail;
    if (failure === "network") throw new TypeError("fetch failed");
    if (typeof failure === "number") {
      return Response.json({ error: { code: "data_unavailable", message: "Historical data is not available on this server." } }, { status: failure });
    }
    const request = String(input).slice(BASE.length + 1);
    const key = options.substitute?.[request] ?? request;
    const hit = RECORDED.responses[key];
    if (!hit) return Response.json({ error: { code: "internal_error", message: `No recording for "${key}"` } }, { status: 500 });
    return Response.json(hit.body, { status: hit.status });
  });
  return { client: createHttpClient({ baseUrl: BASE, fetchImpl }), fetchImpl };
}
