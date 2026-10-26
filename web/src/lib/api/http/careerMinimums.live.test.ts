/**
 * Live checks of the follow-up behaviours (career default, user minimums, several franchises)
 * against a running Baseball API over the real Lahman data.
 *   BASEBALL_API_ORIGIN=http://127.0.0.1:8601 npm run test:live
 */
import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/generated/baseball-api";
import { proxyBaseballApi } from "@/lib/api/proxy";

import { NO_HISTORICAL_FILTERS } from "../types";
import { createHttpClient } from "./httpClient";

type Schemas = components["schemas"];
const ORIGIN = process.env.BASEBALL_API_ORIGIN?.replace(/\/+$/, "");
const API = `${ORIGIN}/api/v1`;

async function direct<T>(path: string): Promise<T> {
  const res = await fetch(`${API}/${path}`);
  return (await res.json()) as T;
}

const he = { yearRange: { start: 2010, end: 2025 }, metric: "HR", order: "desc" as const, playerId: null };
const cabrera = { ...he, metric: "OPS", playerId: "cabremi01" };

describe.skipIf(!ORIGIN)("live: career default, minimums and several franchises", () => {
  const client = createHttpClient({ baseUrl: API });

  it("one player with no chosen years gets the career the API defines", async () => {
    const [result, raw, allPlayers] = await Promise.all([
      client.getHistoricalExplorer({ ...cabrera, explicitRange: { start: false, end: false } }),
      direct<Schemas["SeasonLeadersResult"]>("seasons?metric=OPS&order=desc&player_id=cabremi01&limit=25&include_below_minimum=true"),
      direct<Schemas["SeasonLeadersResult"]>("seasons?metric=OPS&limit=1"),
    ]);
    expect(result.query.yearRange).toEqual({ start: raw.start, end: raw.end });
    expect(raw.start).toBeLessThan(allPlayers.start); // career reaches back before the all-players default
    expect(result.seasons.map((s) => [s.year, s.rank, s.qualified])).toEqual(raw.rows.map((r) => [r.year, r.rank, r.meets_minimum]));
    expect(result.seasons.some((s) => !s.qualified && s.rank === null)).toBe(true);
    expect(result.rankedCount).toBe(raw.ranked_rows);
  });

  it("a chosen bound is preserved; the other stays the career", async () => {
    const [result, raw] = await Promise.all([
      client.getHistoricalExplorer({ ...cabrera, yearRange: { start: 2015, end: 2025 }, explicitRange: { start: true, end: false } }),
      direct<Schemas["SeasonLeadersResult"]>("seasons?start=2015&metric=OPS&order=desc&player_id=cabremi01&limit=25&include_below_minimum=true"),
    ]);
    expect(result.query.yearRange).toEqual({ start: 2015, end: raw.end });
    expect(raw.end).toBeLessThan(2025); // Cabrera's last season, not the all-players end
    expect(result.seasons.every((s) => s.year >= 2015)).toBe(true);
  });

  it("an explicit narrower range is respected", async () => {
    const result = await client.getHistoricalExplorer({ ...cabrera, yearRange: { start: 2015, end: 2020 }, explicitRange: { start: true, end: true } });
    expect(result.query.yearRange).toEqual({ start: 2015, end: 2020 });
    expect(result.seasons.every((s) => s.year >= 2015 && s.year <= 2020)).toBe(true);
  });

  it("minimums: Historical Explorer totals, qualification line and Leaderboards equal the API's", async () => {
    const [hr, rawHr, ops, rawOps, leaders, rawLeaders] = await Promise.all([
      client.getHistoricalExplorer({ ...he, minimums: { ab: 500, stats: {} } }),
      direct<Schemas["SeasonLeadersResult"]>("seasons?start=2010&end=2025&metric=HR&order=desc&min_ab=500&limit=25"),
      client.getHistoricalExplorer({ ...he, metric: "OPS", minimums: { ab: 300, stats: { HR: 30 } } }),
      direct<Schemas["SeasonLeadersResult"]>("seasons?start=2010&end=2025&metric=OPS&order=desc&min_ab=300&min_HR=30&limit=25"),
      client.getLeaderboard({ yearRange: { start: 2020, end: 2025 }, metric: "OPS", minimums: { ab: 1000, stats: { HR: 100 } } }),
      direct<Schemas["LeaderboardResult"]>("leaderboards?start=2020&end=2025&metric=OPS&min_ab=1000&min_HR=100&limit=25"),
    ]);
    expect(hr.totalCount).toBe(rawHr.total_rows);
    expect(ops.totalCount).toBe(rawOps.total_rows);
    expect(ops.qualification.summary).toBe(rawOps.qualification.summary);
    expect(leaders.totalRanked).toBe(rawLeaders.total_rows);
    expect(leaders.entries.map((e) => e.player.id)).toEqual(rawLeaders.rows.map((r) => r.player.player_id));
  });

  it("the API's catalog lists the stats that accept a minimum, and each is accepted", async () => {
    const catalog = await client.getCatalog();
    expect(catalog.historical.filters.minimumColumns.length).toBeGreaterThan(5);
    for (const stat of catalog.historical.filters.minimumColumns) {
      const res = await fetch(`${API}/seasons?start=2025&end=2025&metric=HR&min_${stat}=0&limit=1`);
      expect(res.status, stat).toBe(200);
    }
    expect((await fetch(`${API}/seasons?min_FOO=1&limit=1`)).status).toBe(422);
  });

  it("several franchises: the API's union (Boston + New York = the sum of each)", async () => {
    const team = (t: string) => `seasons?start=2010&end=2025&metric=HR&order=desc&teams=${t}&limit=1`;
    const [both, boston, yankees] = await Promise.all([
      client.getHistoricalExplorer({ ...he, filters: { ...NO_HISTORICAL_FILTERS, teams: ["Boston Red Sox", "New York Yankees"] } }),
      direct<Schemas["SeasonLeadersResult"]>(team("Boston+Red+Sox")),
      direct<Schemas["SeasonLeadersResult"]>(team("New+York+Yankees")),
    ]);
    expect(both.totalCount).toBe(boston.total_rows + yankees.total_rows); // the API's numbers, compared here
    expect(both.seasons.every((s) => ["Boston Red Sox", "New York Yankees"].includes(s.teamName ?? ""))).toBe(true);
  });

  it("the CSV honours the minimums and franchises, byte-for-byte through the proxy", async () => {
    const url = client.historicalExportUrl({
      ...he,
      yearRange: { start: 2025, end: 2025 },
      metric: "OPS",
      minimums: { ab: 300, stats: {} },
      filters: { ...NO_HISTORICAL_FILTERS, teams: ["Boston Red Sox", "New York Yankees"] },
    })!;
    const upstream = await fetch(url);
    const bytes = new Uint8Array(await upstream.arrayBuffer());
    const proxied = await proxyBaseballApi(new Request(`http://web.test/api/baseball/${url.slice(API.length + 1)}`), { origin: ORIGIN });
    expect(proxied.headers.get("content-disposition")).toBe(upstream.headers.get("content-disposition"));
    expect(new Uint8Array(await proxied.arrayBuffer())).toEqual(bytes);
    const rows = new TextDecoder().decode(bytes).split(/\r?\n/).filter(Boolean).length - 1;
    const table = await direct<Schemas["SeasonLeadersResult"]>(url.slice(API.length + 1).replace("&format=csv", "&limit=200"));
    expect(rows).toBe(table.total_rows); // every ranked row, as many as the table says
    expect(rows).toBeGreaterThan(0);
  });
});
