// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { checkReadiness } from "./readiness";

const ORIGIN = "http://internal-api.test:8601";

function health(status: number, body: unknown) {
  return vi.fn<typeof fetch>(async () => new Response(typeof body === "string" ? body : JSON.stringify(body), { status }));
}

afterEach(() => vi.restoreAllMocks());

describe("checkReadiness", () => {
  it("is ready when the API is up and has loaded its data", async () => {
    const fetchImpl = health(200, { status: "ok", build: "abc123", data_loaded: true, seasons: [1871, 2025] });
    expect(await checkReadiness({ origin: ORIGIN, fetchImpl })).toBe("ready");
    const [target, init] = fetchImpl.mock.calls[0]!;
    expect(target).toBe(`${ORIGIN}/api/v1/health`);
    expect(init?.method).toBe("GET");
    expect(init?.cache).toBe("no-store");
    expect(init?.signal).toBeInstanceOf(AbortSignal);
  });

  it("is warming while the API is still reading its data (cold start)", async () => {
    expect(await checkReadiness({ origin: ORIGIN, fetchImpl: health(200, { status: "ok", build: "x", data_loaded: false }) })).toBe("warming");
  });

  it.each([
    ["a 500", health(500, { error: { code: "internal_error", message: "boom" } })],
    ["a 503", health(503, { error: { code: "data_unavailable", message: "loading" } })],
    ["a 404 (wrong origin)", health(404, "not found")],
    ["a non-JSON 200", health(200, "<html>proxy login page</html>")],
    ["an unexpected status word", health(200, { status: "degraded", data_loaded: true })],
    ["a null body", health(200, "null")],
    ["a refused connection", vi.fn<typeof fetch>(async () => { throw new TypeError("fetch failed: ECONNREFUSED 10.0.0.5"); })],
  ])("is unavailable for %s", async (_name, fetchImpl) => {
    expect(await checkReadiness({ origin: ORIGIN, fetchImpl })).toBe("unavailable");
  });

  it("gives up after the bound instead of waiting on a stuck API", async () => {
    const hung = vi.fn<typeof fetch>(
      (_url, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(init.signal!.reason), { once: true });
        }),
    );
    const started = Date.now();
    expect(await checkReadiness({ origin: ORIGIN, fetchImpl: hung, timeoutMs: 50 })).toBe("unavailable");
    expect(Date.now() - started).toBeLessThan(2_000);
  });

  it("reports not_configured, without any request, when there is no origin", async () => {
    const fetchImpl = health(200, {});
    expect(await checkReadiness({ origin: null, fetchImpl })).toBe("not_configured");
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
