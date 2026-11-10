// @vitest-environment node
/**
 * Cold start, end to end through the two layers that handle it: the same-origin proxy
 * (lib/api/proxy.ts, a 30 s bound per request) and the browser client (lib/api/http/httpClient.ts,
 * a 60 s window of retries). Only the Python API is faked. Time is virtual.
 *
 * The behavior these pin down:
 *  - The API does not hold requests while it loads (~18 s): it answers 503 + `Retry-After: 5` at
 *    once. The proxy passes both through; the client waits as told and tries again, for up to 60 s.
 *  - The proxy's 30 s bound only matters for a hung API. That becomes a 502 with no Retry-After,
 *    which the client reports as "unavailable" immediately instead of retrying blindly.
 *  - 30 s is per attempt and 60 s is across attempts, so they do not conflict.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "@/lib/api/generated/baseball-api";
import { recorded } from "@/test/recordedApi";

import { BaseballApiError } from "./errors";
import { createHttpClient } from "./http/httpClient";
import { proxyBaseballApi, type ProxyEvent } from "./proxy";

const ORIGIN = "http://api.test";
const warming = () =>
  Response.json({ error: { code: "data_unavailable", message: "Data is loading." } }, { status: 503, headers: { "retry-after": "5" } });
const catalogOk = () => Response.json(recorded<components["schemas"]["Catalog"]>("catalog"));

/** A browser-side fetch that reaches `upstream` only through the real proxy handler. */
function through(upstream: typeof fetch) {
  const events: ProxyEvent[] = [];
  const fetchImpl: typeof fetch = (input, init) =>
    proxyBaseballApi(new Request(new URL(String(input), "http://web.test"), { signal: init?.signal ?? undefined }), {
      origin: ORIGIN,
      fetchImpl: upstream,
      log: (event) => events.push(event),
    });
  return { client: createHttpClient({ baseUrl: "/api/baseball", fetchImpl }), events };
}

async function failure(promise: Promise<unknown>): Promise<BaseballApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof BaseballApiError) return error;
    throw error;
  }
  throw new Error("expected a rejection");
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("cold start through the proxy and the client", () => {
  it("waits out the API's loading period using its Retry-After, then answers", async () => {
    let calls = 0;
    const upstream = vi.fn<typeof fetch>(async () => (++calls <= 2 ? warming() : catalogOk()));
    const { client, events } = through(upstream);

    const result = client.getCatalog();
    await vi.advanceTimersByTimeAsync(4_999);
    expect(upstream).toHaveBeenCalledTimes(1); // still waiting out the first 5 s
    await vi.advanceTimersByTimeAsync(1);
    expect(upstream).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(5_000);

    expect((await result).years.end).toBe(2025);
    expect(upstream).toHaveBeenCalledTimes(3);
    // Warming is logged as a warning-level category, not as an error.
    expect(events.map((e) => [e.route, e.category, e.status])).toEqual([
      ["catalog", "upstream_warming", 503],
      ["catalog", "upstream_warming", 503],
    ]);
  });

  it("gives up once the 60 s window has passed, and reports the API as unavailable", async () => {
    const upstream = vi.fn<typeof fetch>(async () => warming());
    const { client } = through(upstream);

    const outcome = failure(client.getCatalog());
    await vi.advanceTimersByTimeAsync(70_000);

    const error = await outcome;
    expect(error.kind).toBe("unavailable");
    expect(error.retryAfterSeconds).toBe(5);
    // Attempts at 0, 5, ..., 60 s, plus the one at 65 s that finds the window closed.
    expect(upstream.mock.calls.length).toBeGreaterThanOrEqual(12);
    expect(upstream.mock.calls.length).toBeLessThanOrEqual(14);
    expect(vi.getTimerCount()).toBe(0); // nothing left waiting
  });

  it("does not retry a hung API: the proxy's timeout is a 502 without Retry-After, shown at once", async () => {
    let hung = true;
    const upstream = vi.fn<typeof fetch>(async () => {
      if (hung) throw new DOMException("The operation timed out.", "TimeoutError");
      return catalogOk();
    });
    const { client, events } = through(upstream);

    const error = await failure(client.getCatalog());
    expect(error.kind).toBe("unavailable");
    expect(error.retryAfterSeconds).toBeNull();
    expect(upstream).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
    expect(events.map((e) => [e.category, e.status])).toEqual([["timeout", 502]]);

    // The failure is not remembered: the next call goes back to the API.
    hung = false;
    expect((await client.getCatalog()).years.end).toBe(2025);
    expect(upstream).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["the API's data is missing (503 without Retry-After)", () => Response.json({ error: { code: "data_unavailable", message: "Missing." } }, { status: 503 })],
    ["a server error (500)", () => Response.json({ error: { code: "internal_error", message: "Something went wrong." } }, { status: 500 })],
  ])("does not wait or retry when %s", async (_name, answer) => {
    const upstream = vi.fn<typeof fetch>(async () => answer());
    const { client } = through(upstream);
    const error = await failure(client.getCatalog());
    expect(["unavailable", "unknown"]).toContain(error.kind);
    expect(error.retryAfterSeconds).toBeNull();
    expect(upstream).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not retry when the web app has no API configured", async () => {
    const upstream = vi.fn<typeof fetch>(async () => catalogOk());
    const fetchImpl: typeof fetch = (input) =>
      proxyBaseballApi(new Request(new URL(String(input), "http://web.test")), { origin: null, fetchImpl: upstream, log: () => undefined });
    const error = await failure(createHttpClient({ baseUrl: "/api/baseball", fetchImpl }).getCatalog());
    expect(error.kind).toBe("unavailable");
    expect(error.retryAfterSeconds).toBeNull();
    expect(upstream).not.toHaveBeenCalled();
  });

  it("retries a gateway's own 504 when it says when to come back", async () => {
    let calls = 0;
    const upstream = vi.fn<typeof fetch>(async () =>
      ++calls === 1 ? Response.json({ error: { code: "gateway", message: "Timeout." } }, { status: 504, headers: { "retry-after": "3" } }) : catalogOk(),
    );
    const { client } = through(upstream);
    const result = client.getCatalog();
    await vi.advanceTimersByTimeAsync(3_000);
    expect((await result).years.end).toBe(2025);
    expect(upstream).toHaveBeenCalledTimes(2);
  });

  it("bounds each upstream request at 30 s, shorter than the client's 60 s window", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const upstream = vi.fn<typeof fetch>(async () => catalogOk());
    await through(upstream).client.getCatalog();
    expect(timeout).toHaveBeenCalledWith(30_000);
    expect(upstream.mock.calls[0]![1]?.signal).toBeInstanceOf(AbortSignal);
  });
});
