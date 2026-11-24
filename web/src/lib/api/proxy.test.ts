// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { baseballApiOrigin, logProxyEvent, proxyBaseballApi, type ProxyEvent } from "./proxy";

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

  it.each([
    ["/api/baseball/players/judgeaa01/seasons", "http://api.test/api/v1/players/judgeaa01/seasons"],
    ["/api/baseball/players/judgeaa01", "http://api.test/api/v1/players/judgeaa01"],
    ["/api/baseball/catalog", "http://api.test/api/v1/catalog"],
    ["/api/baseball/players/search?q=judge&limit=8", "http://api.test/api/v1/players/search?q=judge&limit=8"],
  ])("allows %s", async (path, target) => {
    const fetchImpl = upstream(200, {});
    await proxyBaseballApi(get(path), { origin: ORIGIN, fetchImpl });
    expect(fetchImpl.mock.calls[0]![0]).toBe(target);
  });

  it("passes a CSV download through unchanged: bytes, content type and the API's filename", async () => {
    const csv = ["Year,Player,Bats", "2025,Cal Raleigh,B", '2025,"Giménez, André",L', ""].join("\r\n");
    const fetchImpl = vi.fn<typeof fetch>(
      async () =>
        new Response(csv, {
          status: 200,
          headers: {
            "content-type": "text/csv; charset=utf-8",
            "content-disposition": 'attachment; filename="historical_explorer.csv"',
            "content-length": String(csv.length),
            "set-cookie": "x=1",
          },
        }),
    );
    const res = await proxyBaseballApi(get("/api/baseball/seasons?start=2025&end=2025&metric=HR&format=csv"), { origin: ORIGIN, fetchImpl });
    expect(fetchImpl.mock.calls[0]![0]).toBe("http://api.test/api/v1/seasons?start=2025&end=2025&metric=HR&format=csv");
    expect(res.headers.get("content-type")).toBe("text/csv; charset=utf-8");
    expect(res.headers.get("content-disposition")).toBe('attachment; filename="historical_explorer.csv"');
    expect(res.headers.get("set-cookie")).toBeNull();
    expect(await res.text()).toBe(csv);
  });

  it("passes the API's still-loading hint through so the client can wait as told", async () => {
    const res = await proxyBaseballApi(get("/api/baseball/catalog"), {
      origin: ORIGIN,
      fetchImpl: upstream(503, { error: { code: "data_unavailable", message: "loading" } }, { "retry-after": "2" }),
    });
    expect(res.status).toBe(503);
    expect(res.headers.get("retry-after")).toBe("2");
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

describe("Baseball API proxy failure logging", () => {
  const SECRET_QUERY = "q=Shohei+Ohtani&token=abc123";
  const logged = () => {
    const events: ProxyEvent[] = [];
    return { events, log: (event: ProxyEvent) => events.push(event) };
  };

  it("logs a route label, category, status and duration for an unreachable API, and nothing from the request", async () => {
    const { events, log } = logged();
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      throw new TypeError("fetch failed: connect ECONNREFUSED http://10.1.2.3:8601");
    });
    const res = await proxyBaseballApi(get(`/api/baseball/players/ohtansh01/seasons?${SECRET_QUERY}`), { origin: ORIGIN, fetchImpl, log });
    expect(res.status).toBe(502);
    expect(events).toEqual([{ route: "players.seasons", category: "network", status: 502, ms: expect.any(Number) }]);
    expect(JSON.stringify(events)).not.toMatch(/ohtansh01|Ohtani|abc123|token|10\.1\.2\.3|ECONNREFUSED|session=secret|Bearer/);
  });

  it("tells a timeout from other network failures", async () => {
    const { events, log } = logged();
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      throw new DOMException("The operation timed out.", "TimeoutError");
    });
    const res = await proxyBaseballApi(get("/api/baseball/leaderboards?metric=OPS"), { origin: ORIGIN, fetchImpl, log });
    expect(res.status).toBe(502);
    expect(events.map((e) => [e.route, e.category, e.status])).toEqual([["leaderboards", "timeout", 502]]);
  });

  it("logs a 5xx from the API as an error and an API 'still loading' 503 as warming, passing both through", async () => {
    const { events, log } = logged();
    const broken = await proxyBaseballApi(get("/api/baseball/catalog"), {
      origin: ORIGIN,
      fetchImpl: upstream(500, { error: { code: "internal_error", message: "Something went wrong." } }),
      log,
    });
    const warming = await proxyBaseballApi(get("/api/baseball/catalog"), {
      origin: ORIGIN,
      fetchImpl: upstream(503, { error: { code: "data_unavailable", message: "loading" } }, { "retry-after": "5" }),
      log,
    });
    expect([broken.status, warming.status]).toEqual([500, 503]);
    expect(warming.headers.get("retry-after")).toBe("5");
    expect(events.map((e) => [e.category, e.status])).toEqual([["upstream_error", 500], ["upstream_warming", 503]]);
  });

  it("logs a missing origin, and stays quiet for successes, API 4xx answers and refused paths", async () => {
    const { events, log } = logged();
    await proxyBaseballApi(get("/api/baseball/seasons"), { origin: null, fetchImpl: upstream(200, {}), log });
    expect(events.map((e) => [e.route, e.category, e.status])).toEqual([["seasons", "not_configured", 503]]);

    events.length = 0;
    await proxyBaseballApi(get("/api/baseball/seasons"), { origin: ORIGIN, fetchImpl: upstream(200, {}), log });
    await proxyBaseballApi(get("/api/baseball/leaderboards?metric=WAR"), { origin: ORIGIN, fetchImpl: upstream(422, { error: { code: "invalid_metric", message: "x" } }), log });
    await proxyBaseballApi(get("/api/baseball/admin?x=1"), { origin: ORIGIN, fetchImpl: upstream(200, {}), log });
    expect(events).toEqual([]);
  });

  it("does not log a request the browser itself abandoned", async () => {
    const { events, log } = logged();
    const controller = new AbortController();
    const request = new Request("http://web.test/api/baseball/seasons", { signal: controller.signal });
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      controller.abort();
      throw new DOMException("aborted", "AbortError");
    });
    const res = await proxyBaseballApi(request, { origin: ORIGIN, fetchImpl, log });
    expect(res.status).toBe(499);
    expect(events).toEqual([]);
  });

  describe("default sink", () => {
    afterEach(() => vi.restoreAllMocks());

    it("writes one JSON line: errors to console.error, warming to console.warn", () => {
      const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
      const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
      logProxyEvent({ route: "seasons", category: "timeout", status: 502, ms: 30001 });
      logProxyEvent({ route: "catalog", category: "upstream_warming", status: 503, ms: 12 });
      expect(JSON.parse(error.mock.calls[0]![0] as string)).toEqual({ event: "baseball_proxy", route: "seasons", category: "timeout", status: 502, ms: 30001 });
      expect(JSON.parse(warn.mock.calls[0]![0] as string)).toMatchObject({ category: "upstream_warming", status: 503 });
    });
  });
});
