// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { baseballApiOrigin, proxyBaseballApi } from "./proxy";

const ORIGIN = "http://api.test";

function upstream(status: number, body: unknown, headers: Record<string, string> = {}) {
  return vi.fn<typeof fetch>(async () =>
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } }),
  );
}

const get = (path: string) => new Request(`http://web.test${path}`, { headers: { cookie: "session=secret", authorization: "Bearer x" } });

describe("Baseball API proxy", () => {
  it("forwards an allowed GET with its query to /api/v1 and returns the API's response untouched", async () => {
    const fetchImpl = upstream(200, { rows: [] }, { "server-timing": "business;dur=91", "cache-control": "public, max-age=300", "set-cookie": "x=1" });
    const res = await proxyBaseballApi(get("/api/baseball/leaderboards?metric=OPS&start=2020"), { origin: ORIGIN, fetchImpl });

    expect(fetchImpl).toHaveBeenCalledOnce();
    const [target, init] = fetchImpl.mock.calls[0]!;
    expect(target).toBe("http://api.test/api/v1/leaderboards?metric=OPS&start=2020");
    expect(new Headers(init?.headers).get("cookie")).toBeNull();
    expect(new Headers(init?.headers).get("authorization")).toBeNull();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ rows: [] });
    expect(res.headers.get("server-timing")).toBe("business;dur=91");
    expect(res.headers.get("set-cookie")).toBeNull();
  });

  it("passes API errors through with their status and envelope", async () => {
    const body = { error: { code: "invalid_metric", message: "'WAR' is not a Leaderboards stat." } };
    const res = await proxyBaseballApi(get("/api/baseball/leaderboards?metric=WAR"), { origin: ORIGIN, fetchImpl: upstream(422, body) });
    expect(res.status).toBe(422);
    expect(await res.json()).toEqual(body);
  });

  it.each([
    "/api/baseball/openapi.json",
    "/api/baseball/players/resolve?name=x",
    "/api/baseball/players/judgeaa01/career",
    "/api/baseball/../admin",
    "/api/baseball/",
  ])("refuses %s without calling the API", async (path) => {
    const fetchImpl = upstream(200, {});
    const res = await proxyBaseballApi(get(path), { origin: ORIGIN, fetchImpl });
    expect(res.status).toBe(404);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("allows the player seasons path for a Lahman id", async () => {
    const fetchImpl = upstream(200, {});
    await proxyBaseballApi(get("/api/baseball/players/judgeaa01/seasons"), { origin: ORIGIN, fetchImpl });
    expect(fetchImpl.mock.calls[0]![0]).toBe("http://api.test/api/v1/players/judgeaa01/seasons");
  });

  it("reports an unreachable API as 502 upstream_unavailable", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      throw new TypeError("fetch failed");
    });
    const res = await proxyBaseballApi(get("/api/baseball/seasons"), { origin: ORIGIN, fetchImpl });
    expect(res.status).toBe(502);
    expect((await res.json()).error.code).toBe("upstream_unavailable");
  });

  it("refuses to guess an origin in production", async () => {
    expect(baseballApiOrigin({ NODE_ENV: "production" })).toBeNull();
    expect(baseballApiOrigin({ NODE_ENV: "development" })).toBe("http://127.0.0.1:8601");
    expect(baseballApiOrigin({ NODE_ENV: "production", BASEBALL_API_ORIGIN: "https://api.example/" })).toBe("https://api.example");
    const res = await proxyBaseballApi(get("/api/baseball/seasons"), { origin: null, fetchImpl: upstream(200, {}) });
    expect(res.status).toBe(503);
    expect((await res.json()).error.code).toBe("upstream_not_configured");
  });
});
