/**
 * Live integration tests: the HTTP adapter, and the proxy, against a running Baseball API over
 * the real Lahman data.
 *   BASEBALL_API_ORIGIN=http://127.0.0.1:8601 npm run test:live
 * Every expectation is read from the API itself (a direct request), never typed in by hand.
 */
import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/generated/baseball-api";
import { proxyBaseballApi } from "@/lib/api/proxy";
import meta from "../../../../openapi/baseball-api.meta.json";

import { BaseballApiError } from "../errors";
import { NO_HISTORICAL_FILTERS } from "../types";
import { createHttpClient } from "./httpClient";

type Schemas = components["schemas"];
const ORIGIN = process.env.BASEBALL_API_ORIGIN?.replace(/\/+$/, "");
const API = `${ORIGIN}/api/v1`;

async function direct<T>(path: string): Promise<{ status: number; body: T }> {
  const res = await fetch(`${API}/${path}`);
  return { status: res.status, body: (await res.json()) as T };
}

/** The value a column's field path points at, looked up independently of the adapter's code. */
function pick(row: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((value, key) => (value && typeof value === "object" ? (value as Record<string, unknown>)[key] : undefined), row) ?? null;
}

const he = { yearRange: { start: 2010, end: 2025 }, metric: "HR", order: "desc" as const, playerId: null };
const lb = { yearRange: { start: 2020, end: 2025 }, metric: "score" };

describe.skipIf(!ORIGIN)(`live Baseball API (pinned ${meta.api_commit})`, () => {
  const client = createHttpClient({ baseUrl: API });

  it("serves the pinned schema", async () => {
    const { body } = await direct<{ info: { version: string }; paths: Record<string, unknown> }>("openapi.json");
    expect(body.info.version).toBe(meta.api_version);
    expect(Object.keys(body.paths).sort()).toEqual([
      "/api/v1/catalog",
      "/api/v1/health",
      "/api/v1/leaderboards",
      "/api/v1/players/resolve",
      "/api/v1/players/search",
      "/api/v1/players/{player_id}",
      "/api/v1/players/{player_id}/seasons",
      "/api/v1/seasons",
    ]);
  });

  it("the catalog is the API's catalog, and its defaults are what the endpoints apply", async () => {
    const [catalog, raw, seasons, leaders] = await Promise.all([
      client.getCatalog(),
      direct<Schemas["Catalog"]>("catalog"),
      direct<Schemas["SeasonLeadersResult"]>("seasons?limit=1"),
      direct<Schemas["LeaderboardResult"]>("leaderboards?limit=1"),
    ]);
    expect(catalog.years).toEqual({ start: raw.body.seasons.first, end: raw.body.seasons.last });
    expect(catalog.historical.columns).toEqual(raw.body.historical.columns);
    expect(catalog.leaderboards.columns).toEqual(raw.body.leaderboards.columns);
    expect(catalog.metrics.find((m) => m.key === "HR")?.name).toBe(raw.body.metrics.find((m) => m.key === "HR")?.name);
    expect(catalog.historical.yearRange).toEqual({ start: seasons.body.start, end: seasons.body.end });
    expect([catalog.historical.metric, catalog.historical.order]).toEqual([seasons.body.metric.key, seasons.body.order]);
    expect(catalog.leaderboards.yearRange).toEqual({ start: leaders.body.start, end: leaders.body.end });
    expect(catalog.leaderboards.metric).toBe(leaders.body.metric.key);
    expect(catalog.leaderboards.weights).toEqual(leaders.body.weights);
  });

  it("every Historical Explorer metric in the catalog is accepted by the API", async () => {
    const catalog = await client.getCatalog();
    for (const metric of catalog.historical.metrics) {
      const { status } = await direct(`seasons?metric=${encodeURIComponent(metric)}&limit=1`);
      expect(status, metric).toBe(200);
    }
  });

  it("maps a live Historical Explorer answer, rows and table cells faithfully", async () => {
    const [result, raw, catalog] = await Promise.all([
      client.getHistoricalExplorer({ ...he, metric: "OPS" }),
      direct<Schemas["SeasonLeadersResult"]>("seasons?start=2010&end=2025&metric=OPS&order=desc&limit=25"),
      direct<Schemas["Catalog"]>("catalog"),
    ]);
    expect(result.answer).toEqual({ headline: raw.body.answer!.headline, detail: raw.body.answer!.body, context: raw.body.answer!.context });
    expect(result.keyMetrics).toEqual(raw.body.answer!.tile_metrics);
    expect(result.totalCount).toBe(raw.body.total_rows);
    expect(result.qualification.summary).toBe(raw.body.qualification.summary);
    expect(result.table.columns.map((c) => c.label)).toEqual(catalog.body.historical.columns.map((c) => c.label));
    raw.body.rows.forEach((row, r) => {
      catalog.body.historical.columns.forEach((column, c) => {
        expect(result.table.rows[r]!.cells[c], `${row.player.name} ${column.label}`).toBe(pick(row, column.field));
      });
    });
  });

  it("pages continue the ranking", async () => {
    const [page2, raw] = await Promise.all([
      client.getHistoricalExplorer({ ...he, offset: 25 }),
      direct<Schemas["SeasonLeadersResult"]>("seasons?start=2010&end=2025&metric=HR&order=desc&limit=25&offset=25"),
    ]);
    expect(page2.seasons.map((s) => s.rank)).toEqual(raw.body.rows.map((r) => r.rank));
    expect(page2.seasons[0]!.rank).toBe(26);
  });

  it("applies filters in the API", async () => {
    const [result, raw] = await Promise.all([
      client.getHistoricalExplorer({ ...he, filters: { ...NO_HISTORICAL_FILTERS, bats: ["L"], positions: ["SS"] } }),
      direct<Schemas["SeasonLeadersResult"]>("seasons?start=2010&end=2025&metric=HR&order=desc&bats=L&positions=SS&position_source=season&limit=25"),
    ]);
    expect(result.totalCount).toBe(raw.body.total_rows);
    expect(result.seasons.map((s) => s.player.id)).toEqual(raw.body.rows.map((r) => r.player.player_id));
    expect(result.totalCount).toBeLessThan((await direct<Schemas["SeasonLeadersResult"]>("seasons?start=2010&end=2025&metric=HR&limit=1")).body.total_rows);
  });

  it("ranks one player's seasons and marks those below the minimum", async () => {
    const [result, raw] = await Promise.all([
      client.getHistoricalExplorer({ ...he, metric: "OPS", playerId: "judgeaa01" }),
      direct<Schemas["SeasonLeadersResult"]>("seasons?start=2010&end=2025&metric=OPS&order=desc&player_id=judgeaa01&limit=25&include_below_minimum=true"),
    ]);
    expect(result.seasons.map((s) => [s.rank, s.qualified])).toEqual(raw.body.rows.map((r) => [r.rank, r.meets_minimum]));
    expect(result.seasons.some((s) => !s.qualified && s.rank === null)).toBe(true);
    expect(result.chart?.kind).toBe("timeline");
  });

  it("maps a live leaderboard, its table and custom weights faithfully", async () => {
    const [result, raw, catalog, weighted, rawWeighted] = await Promise.all([
      client.getLeaderboard(lb),
      direct<Schemas["LeaderboardResult"]>("leaderboards?start=2020&end=2025&metric=score&limit=25"),
      direct<Schemas["Catalog"]>("catalog"),
      client.getLeaderboard({ ...lb, weights: { HR: 2, RBI: 1 } }),
      direct<Schemas["LeaderboardResult"]>("leaderboards?start=2020&end=2025&metric=score&weights=HR%3A2%2CRBI%3A1&limit=25"),
    ]);
    expect(result.entries.map((e) => [e.rank, e.player.id, e.stats.score])).toEqual(raw.body.rows.map((r) => [r.rank, r.player.player_id, r.score]));
    expect(result.answer?.headline).toBe(raw.body.answer!.headline);
    raw.body.rows.forEach((row, r) => {
      catalog.body.leaderboards.columns.forEach((column, c) => {
        expect(result.table.rows[r]!.cells[c], `${row.player.name} ${column.label}`).toBe(pick(row, column.field));
      });
    });
    expect(weighted.entries.map((e) => e.player.id)).toEqual(rawWeighted.body.rows.map((r) => r.player.player_id));
    expect(weighted.entries.map((e) => e.stats.score)).not.toEqual(result.entries.map((e) => e.stats.score));
  });

  it("the CSV header is the catalog's column labels, through the adapter's link and the proxy", async () => {
    const catalog = (await direct<Schemas["Catalog"]>("catalog")).body;
    const query = { ...he, yearRange: { start: 2025, end: 2025 }, filters: { ...NO_HISTORICAL_FILTERS, bats: ["B"], positions: ["C"] } };
    const url = client.historicalExportUrl(query);
    expect(url).toBeTruthy();
    const upstream = await fetch(url!);
    const bytes = new Uint8Array(await upstream.arrayBuffer());
    expect(upstream.headers.get("content-type")).toMatch(/^text\/csv/);
    expect(upstream.headers.get("content-disposition")).toBe('attachment; filename="historical_explorer.csv"');
    expect(new TextDecoder().decode(bytes).split(/\r?\n/)[0]).toBe(catalog.historical.columns.map((c) => c.label).join(","));

    // Through the proxy: same status, headers that matter, and byte-for-byte the same file.
    const proxied = await proxyBaseballApi(new Request(`http://web.test/api/baseball/${url!.slice(API.length + 1)}`), { origin: ORIGIN });
    expect(proxied.status).toBe(200);
    expect(proxied.headers.get("content-type")).toBe(upstream.headers.get("content-type"));
    expect(proxied.headers.get("content-disposition")).toBe(upstream.headers.get("content-disposition"));
    expect(new Uint8Array(await proxied.arrayBuffer())).toEqual(bytes);

    // Leaderboards: the Top N export, with its own filename.
    const lbUrl = client.leaderboardExportUrl({ ...lb, metric: "OPS", limit: 25 })!;
    const lbProxied = await proxyBaseballApi(new Request(`http://web.test/api/baseball/${lbUrl.slice(API.length + 1)}`), { origin: ORIGIN });
    expect(lbProxied.headers.get("content-disposition")).toBe('attachment; filename="leaderboards.csv"');
    expect((await lbProxied.text()).split(/\r?\n/)[0]).toBe(catalog.leaderboards.columns.map((c) => c.label).join(","));
  });

  it("maps live errors to the page's error kinds", async () => {
    const bad = await client.getLeaderboard({ yearRange: { start: 2020, end: 2025 }, metric: "WAR" }).catch((e: unknown) => e);
    expect(bad).toBeInstanceOf(BaseballApiError);
    expect((bad as BaseballApiError).kind).toBe("invalid_request");
    const range = await client.getHistoricalExplorer({ ...he, yearRange: { start: 2030, end: 2031 } }).catch((e: unknown) => e);
    expect((range as BaseballApiError).kind).toBe("invalid_request");
  });

  it("searches players, reads a player, and treats an unknown id as no player", async () => {
    const players = await client.searchPlayers("judge");
    expect(players.some((p) => p.id === "judgeaa01")).toBe(true);
    expect((await client.getPlayer("judgeaa01"))?.id).toBe("judgeaa01");
    expect(await client.getPlayer("nobody99")).toBeNull();
  });
});
