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

interface JsonRecording {
  status: number;
  body: unknown;
}

interface CsvRecording {
  status: number;
  contentType: string;
  contentDisposition: string | null;
  text: string;
}

type Recording = JsonRecording | CsvRecording;

export const RECORDED = recordedFile as unknown as { api_commit: string; recorded_at: string; responses: Record<string, Recording> };
const BASE = "http://recorded.test/api/v1";

export function recorded<T = Record<string, unknown>>(request: string): T {
  const hit = RECORDED.responses[request];
  if (!hit || !("body" in hit)) throw new Error(`No JSON recording for "${request}"`);
  return hit.body as T;
}

export function recordedCsv(request: string): CsvRecording {
  const hit = RECORDED.responses[request];
  if (!hit || !("text" in hit)) throw new Error(`No CSV recording for "${request}"`);
  return hit;
}

/** A `Response` for a recording, exactly as the API sent it. */
export function responseFor(hit: Recording): Response {
  if ("text" in hit) {
    const headers = new Headers({ "content-type": hit.contentType });
    if (hit.contentDisposition) headers.set("content-disposition", hit.contentDisposition);
    return new Response(hit.text, { status: hit.status, headers });
  }
  return Response.json(hit.body, { status: hit.status });
}

export interface RecordedClientOptions {
  /** Serve one recording in place of another: { "<request sent>": "<recording to return>" }. */
  substitute?: Record<string, string>;
  /** Make the transport fail ("network") or return a status without calling the recording. */
  fail?: "network" | number | (() => "network" | number | null);
  /** Respond to the catalog request with 503 + Retry-After this many times first (a cold start). */
  warmingUp?: number;
}

export function createRecordedClient(options: RecordedClientOptions = {}): { client: BaseballClient; fetchImpl: ReturnType<typeof vi.fn<typeof fetch>> } {
  let warming = options.warmingUp ?? 0;
  const fetchImpl = vi.fn<typeof fetch>(async (input, init) => {
    if (init?.signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const failure = typeof options.fail === "function" ? options.fail() : options.fail;
    if (failure === "network") throw new TypeError("fetch failed");
    if (typeof failure === "number") {
      return Response.json({ error: { code: "data_unavailable", message: "Historical data is not available on this server." } }, { status: failure });
    }
    const request = String(input).slice(BASE.length + 1);
    if (request === "catalog" && warming > 0) {
      warming -= 1;
      return Response.json(
        { error: { code: "data_unavailable", message: "Historical data is still loading." } },
        { status: 503, headers: { "retry-after": "0.01" } },
      );
    }
    const key = options.substitute?.[request] ?? request;
    const hit = RECORDED.responses[key];
    if (!hit) return Response.json({ error: { code: "internal_error", message: `No recording for "${key}"` } }, { status: 500 });
    return responseFor(hit);
  });
  return { client: createHttpClient({ baseUrl: BASE, fetchImpl }), fetchImpl };
}
