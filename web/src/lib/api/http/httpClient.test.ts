import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/generated/baseball-api";
import { createRecordedClient, RECORDED, recorded } from "@/test/recordedApi";

import { BaseballApiError } from "../errors";
import { NO_HISTORICAL_FILTERS } from "../types";

type Schemas = components["schemas"];

const HE = "seasons?start=2010&end=2025&metric=HR&order=desc&limit=25";
const HE_OPS = "seasons?start=2010&end=2025&metric=OPS&order=desc&limit=25";
const HE_PAGE2 = `${HE}&offset=25`;
const HE_FILTERED = "seasons?start=2010&end=2025&metric=HR&order=desc&bats=L&positions=SS&position_source=season&limit=25";
const HE_JUDGE = "seasons?start=2010&end=2025&metric=OPS&order=desc&player_id=judgeaa01&limit=25&include_below_minimum=true";
const LB = "leaderboards?start=2020&end=2025&metric=score&limit=25";
const LB_OPS = "leaderboards?start=2020&end=2025&metric=OPS&limit=25";
const LB_WEIGHTED = "leaderboards?start=2020&end=2025&metric=score&weights=HR%3A2%2CRBI%3A1&limit=25";

const he = { yearRange: { start: 2010, end: 2025 }, metric: "HR", order: "desc" as const, playerId: null };
const lb = { yearRange: { start: 2020, end: 2025 }, metric: "score" };

async function rejection(promise: Promise<unknown>): Promise<BaseballApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof BaseballApiError) return error;
    throw error;
  }
  throw new Error("expected a rejection");
}

/** The value a column's field path points at, looked up independently of the adapter's code. */
function pick(row: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((value, key) => (value && typeof value === "object" ? (value as Record<string, unknown>)[key] : undefined), row) ?? null;
}

describe("HTTP adapter over recorded real API responses (5ca7a26)", () => {
  it("is the real API, with every capability on", () => {
    const { client } = createRecordedClient();
    expect(RECORDED.api_commit).toBe("5ca7a26");
    expect(client.source).toBe("api");
    expect(client.capabilities).toEqual({ playerSeasonRanking: true, csvExport: true, paging: true });
  });

  describe("catalog", () => {
    it("copies the API's lists, labels, plain names, columns and filters", async () => {
      const raw = recorded<Schemas["Catalog"]>("catalog");
      const catalog = await createRecordedClient().client.getCatalog();
      expect(catalog.years).toEqual({ start: raw.seasons.first, end: raw.seasons.last });
      expect(catalog.metrics.map((m) => [m.key, m.label, m.name, m.format])).toEqual(raw.metrics.map((m) => [m.key, m.label, m.name, m.kind]));
      expect(catalog.metrics.find((m) => m.key === "HR")?.name).toBe("home runs");
      expect(catalog.metrics.find((m) => m.key === "yearID")?.format).toBe("year");
      expect(catalog.historical.metrics).toEqual(raw.historical.metrics);
      expect(catalog.historical.columns).toEqual(raw.historical.columns);
      expect(catalog.leaderboards.columns).toEqual(raw.leaderboards.columns);
      expect(catalog.historical.filters.teams).toEqual(raw.historical.filters.teams);
      expect(catalog.historical.filters.bats.map((b) => b.value)).toEqual(["B", "L", "R"]);
      expect(catalog.leaderboards).toMatchObject({
        limit: raw.leaderboards.defaults.limit,
        limitBounds: raw.leaderboards.limit_bounds,
        weightBounds: raw.leaderboards.weight_bounds,
        weightStep: raw.leaderboards.weight_step,
        weights: raw.leaderboards.defaults.weights,
      });
    });

    it("defaults equal what the API applies when nothing is sent", async () => {
      const catalog = await createRecordedClient().client.getCatalog();
      const seasons = recorded<Schemas["SeasonLeadersResult"]>("seasons");
      const leaders = recorded<Schemas["LeaderboardResult"]>("leaderboards");
      expect(catalog.historical.yearRange).toEqual({ start: seasons.start, end: seasons.end });
      expect([catalog.historical.metric, catalog.historical.order]).toEqual([seasons.metric.key, seasons.order]);
      expect(catalog.leaderboards.yearRange).toEqual({ start: leaders.start, end: leaders.end });
      expect(catalog.leaderboards.metric).toBe(leaders.metric.key);
    });

    it("is fetched once per client, and a failure isn't remembered", async () => {
      const { client, fetchImpl } = createRecordedClient();
      await Promise.all([client.getCatalog(), client.getCatalog(), client.getHistoricalExplorer(he)]);
      expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/catalog"))).toHaveLength(1);

      let down = true;
      const flaky = createRecordedClient({ fail: () => (down ? "network" : null) });
      expect((await rejection(flaky.client.getCatalog())).kind).toBe("unavailable");
      down = false;
      expect((await flaky.client.getCatalog()).years.end).toBe(2025);
    });

    it("waits out the API's cold start (503 + Retry-After) before answering", async () => {
      const { client, fetchImpl } = createRecordedClient({ warmingUp: 2 });
      const catalog = await client.getCatalog();
      expect(catalog.years.end).toBe(2025);
      expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/catalog"))).toHaveLength(3);
    });
  });

  describe("Historical Explorer", () => {
    it("shows the API's answer, tile list and rows without changing them", async () => {
      const raw = recorded<Schemas["SeasonLeadersResult"]>(HE);
      const result = await createRecordedClient().client.getHistoricalExplorer(he);

      expect(result.answer).toEqual({ headline: raw.answer!.headline, detail: raw.answer!.body, context: raw.answer!.context });
      expect(result.keyMetrics).toEqual(raw.answer!.tile_metrics);
      expect(result.totalCount).toBe(raw.total_rows);
      expect(result.rankedCount).toBe(raw.ranked_rows);
      expect(result.offset).toBe(0);
      expect(result.seasons).toHaveLength(raw.rows.length);
      raw.rows.forEach((row, i) => {
        const season = result.seasons[i]!;
        expect(season.player).toEqual({ id: row.player.player_id, name: row.player.name });
        expect(season.year).toBe(row.year);
        expect(season.rank).toBe(row.rank);
        expect(season.qualified).toBe(row.meets_minimum);
        expect(season.teamName).toBe(row.team?.season_name ?? row.team?.name ?? null);
        for (const [key, value] of Object.entries(row.stats)) expect(season.stats[key]).toBe(value);
      });
      expect(result.topSeasonId).toBe(result.seasons[0]!.id);
      expect(result.chart).toMatchObject({ kind: "ranking" });
      expect(result.chart!.seasonIds).toEqual(result.seasons.slice(0, 10).map((s) => s.id));
      expect(result.metric).toEqual({ key: "HR", label: raw.metric.label, name: "home runs", format: "count" });
    });

    it("renders the table in the API's column order from each column's field path", async () => {
      const raw = recorded<Schemas["SeasonLeadersResult"]>(HE);
      const catalog = recorded<Schemas["Catalog"]>("catalog");
      const { table } = await createRecordedClient().client.getHistoricalExplorer(he);

      expect(table.columns.map((c) => c.label)).toEqual(catalog.historical.columns.map((c) => c.label));
      expect(table.columns.map((c) => c.field)).toEqual(catalog.historical.columns.map((c) => c.field));
      raw.rows.forEach((row, r) => {
        expect(table.rows[r]!.rank).toBe(row.rank);
        catalog.historical.columns.forEach((column, c) => {
          expect(table.rows[r]!.cells[c], `${row.player.name} ${column.label}`).toBe(pick(row as unknown as Record<string, unknown>, column.field));
        });
      });
    });

    it("qualification: the API's chip line and explanation; its Markdown caption is never used", async () => {
      const raw = recorded<Schemas["SeasonLeadersResult"]>(HE_OPS);
      const result = await createRecordedClient().client.getHistoricalExplorer({ ...he, metric: "OPS" });
      expect(raw.qualification.text).toContain("**");
      expect(result.qualification).toEqual({
        kind: "qualified",
        summary: raw.qualification.summary,
        explanation: raw.qualification.explanation,
        minAtBats: raw.qualification.min_ab,
        scope: "season",
      });
      expect(result.qualification.summary).not.toMatch(/\*|Stat minimum filters/);
      expect(result.metric.format).toBe("rate");
      // Counting stats have no chip line.
      const counting = await createRecordedClient().client.getHistoricalExplorer(he);
      expect(counting.qualification).toMatchObject({ kind: "not_applicable", summary: null });
    });

    it("pages by offset: the second page continues the ranking", async () => {
      const raw = recorded<Schemas["SeasonLeadersResult"]>(HE_PAGE2);
      const result = await createRecordedClient().client.getHistoricalExplorer({ ...he, offset: 25 });
      expect(result.offset).toBe(25);
      expect(result.seasons.map((s) => s.rank)).toEqual(raw.rows.map((r) => r.rank));
      expect(result.seasons[0]!.rank).toBe(26);
      expect(result.topSeasonId).toBeNull(); // the answer's season is on page one
      expect(result.chart).toBeNull();
      expect(result.table.rows[0]!.rank).toBe(26);
    });

    it("sends filters as API parameters", async () => {
      const { client, fetchImpl } = createRecordedClient();
      const raw = recorded<Schemas["SeasonLeadersResult"]>(HE_FILTERED);
      const result = await client.getHistoricalExplorer({
        ...he,
        filters: { ...NO_HISTORICAL_FILTERS, bats: ["L"], positions: ["SS"] },
      });
      expect(fetchImpl.mock.calls.some(([url]) => String(url).endsWith(HE_FILTERED))).toBe(true);
      expect(result.totalCount).toBe(raw.total_rows);
      expect(result.seasons.map((s) => s.player.id)).toEqual(raw.rows.map((r) => r.player.player_id));
    });

    it("one player: ranked seasons first, below-minimum seasons marked and unranked", async () => {
      const raw = recorded<Schemas["SeasonLeadersResult"]>(HE_JUDGE);
      const { client, fetchImpl } = createRecordedClient();
      const result = await client.getHistoricalExplorer({ ...he, metric: "OPS", playerId: "judgeaa01" });
      expect(fetchImpl.mock.calls.some(([url]) => String(url).includes("include_below_minimum=true"))).toBe(true);

      expect(result.query.playerId).toBe("judgeaa01");
      expect(result.chart).toMatchObject({ kind: "timeline" });
      expect(result.chart!.seasonIds).toHaveLength(raw.rows.length);
      const below = result.seasons.filter((s) => !s.qualified);
      expect(below.length).toBeGreaterThan(0);
      expect(below.every((s) => s.rank === null)).toBe(true);
      expect(result.seasons.filter((s) => s.qualified).map((s) => s.rank)).toEqual(
        raw.rows.filter((r) => r.meets_minimum).map((r) => r.rank),
      );
      expect(result.table.rows.filter((r) => r.note).length).toBe(below.length);
      expect(result.rankedCount).toBe(raw.ranked_rows);
      expect(result.totalCount).toBe(raw.total_rows);
      expect(result.answer?.headline).toBe(raw.answer!.headline);
    });

    it("maps a real empty result to no rows, no answer and an empty table", async () => {
      const { client } = createRecordedClient({ substitute: { [HE]: `${HE}&min_HR=100` } });
      const result = await client.getHistoricalExplorer(he);
      expect(result.seasons).toEqual([]);
      expect(result.answer).toBeNull();
      expect(result.chart).toBeNull();
      expect(result.table.rows).toEqual([]);
    });
  });

  describe("Leaderboards", () => {
    it("copies the answer, ranking and score weights, with no invented fields", async () => {
      const raw = recorded<Schemas["LeaderboardResult"]>(LB);
      const result = await createRecordedClient().client.getLeaderboard(lb);

      expect(result.answer).toEqual({ headline: raw.answer!.headline, detail: raw.answer!.body, context: raw.answer!.context });
      expect(result.totalRanked).toBe(raw.total_rows);
      raw.rows.forEach((row, i) => {
        const entry = result.entries[i]!;
        expect(entry.rank).toBe(row.rank);
        expect(entry.player.id).toBe(row.player.player_id);
        expect(entry.stats.score).toBe(row.score);
        expect(entry.stats.HR).toBe(row.stats.HR);
      });
      expect(result.score).toEqual({ weights: Object.entries(raw.weights).map(([metric, weight]) => ({ metric, weight })) });
      expect(result.query.limit).toBe(25);
    });

    it("renders the table in the API's column order from each column's field path", async () => {
      const raw = recorded<Schemas["LeaderboardResult"]>(LB);
      const catalog = recorded<Schemas["Catalog"]>("catalog");
      const { table } = await createRecordedClient().client.getLeaderboard(lb);
      expect(table.columns.map((c) => c.label)).toEqual(catalog.leaderboards.columns.map((c) => c.label));
      expect(table.columns.at(-1)).toMatchObject({ label: "Score", field: "score", metric: "score" });
      raw.rows.forEach((row, r) => {
        catalog.leaderboards.columns.forEach((column, c) => {
          expect(table.rows[r]!.cells[c], `${row.player.name} ${column.label}`).toBe(pick(row as unknown as Record<string, unknown>, column.field));
        });
      });
    });

    it("sends Top N and custom weights as API parameters", async () => {
      const { client, fetchImpl } = createRecordedClient();
      const raw = recorded<Schemas["LeaderboardResult"]>(LB_WEIGHTED);
      const result = await client.getLeaderboard({ ...lb, weights: { HR: 2, RBI: 1 } });
      expect(fetchImpl.mock.calls.some(([url]) => String(url).endsWith(LB_WEIGHTED))).toBe(true);
      expect(result.entries.map((e) => e.player.id)).toEqual(raw.rows.map((r) => r.player.player_id));
      expect(result.score?.weights).toEqual([{ metric: "HR", weight: 2 }, { metric: "RBI", weight: 1 }]);

      const top10 = await createRecordedClient().client.getLeaderboard({ ...lb, limit: 10 });
      expect(top10.entries).toHaveLength(10);
    });

    it("carries the span qualification for rate-stat leaderboards", async () => {
      const raw = recorded<Schemas["LeaderboardResult"]>(LB_OPS);
      const result = await createRecordedClient().client.getLeaderboard({ ...lb, metric: "OPS" });
      expect(result.qualification).toEqual({
        kind: "qualified",
        summary: raw.qualification.summary,
        explanation: raw.qualification.explanation,
        minAtBats: raw.qualification.min_ab,
        scope: "span",
      });
    });
  });

  describe("players", () => {
    it("uses the API's unique labels in search results", async () => {
      const raw = recorded<Schemas["PlayerSearchResult"]>("players/search?q=judge&limit=8");
      const { client } = createRecordedClient();
      const players = await client.searchPlayers("judge");
      expect(players.map((p) => p.name)).toEqual(raw.results.map((r) => r.player.label));
      expect(players[0]).toMatchObject({ id: raw.results[0]!.player.player_id, firstSeason: raw.results[0]!.first_season });
      expect(await client.searchPlayers("j")).toEqual([]);
    });

    it("reads a player's summary, and treats an unknown id as no player", async () => {
      const { client } = createRecordedClient();
      expect((await client.getPlayer("judgeaa01"))?.name).toBe(recorded<Schemas["PlayerSummary"]>("players/judgeaa01").player.label);
      expect(await client.getPlayer("nobody99")).toBeNull();
    });
  });

  describe("CSV export links", () => {
    it("link to the API's CSV through the proxy, without building any file", () => {
      const { client } = createRecordedClient();
      const url = client.historicalExportUrl({ ...he, filters: { ...NO_HISTORICAL_FILTERS, bats: ["B"], positions: ["C"] }, offset: 25 });
      expect(url).toBe("http://recorded.test/api/v1/seasons?start=2010&end=2025&metric=HR&order=desc&bats=B&positions=C&position_source=season&format=csv");
      expect(client.leaderboardExportUrl({ ...lb, metric: "OPS", limit: 25 })).toBe(
        "http://recorded.test/api/v1/leaderboards?start=2020&end=2025&metric=OPS&limit=25&format=csv",
      );
    });
  });

  it("maps API errors and transport failures to the page's error kinds", async () => {
    const real422 = await rejection(createRecordedClient().client.getHistoricalExplorer({ ...he, metric: "WAR" }));
    expect(real422.kind).toBe("invalid_request");
    expect(real422.message).toBe(recorded<Schemas["ErrorResponse"]>("seasons?start=2010&end=2025&metric=WAR&order=desc&limit=25").error.message);

    expect((await rejection(createRecordedClient().client.getLeaderboard({ yearRange: { start: 2030, end: 2031 }, metric: "HR" }))).kind).toBe("invalid_request");
    expect((await rejection(createRecordedClient({ fail: "network" }).client.getLeaderboard(lb))).kind).toBe("unavailable");
    expect((await rejection(createRecordedClient({ fail: 503 }).client.getLeaderboard(lb))).kind).toBe("unavailable");
    expect((await rejection(createRecordedClient({ fail: 502 }).client.getLeaderboard(lb))).kind).toBe("unavailable");
    expect((await rejection(createRecordedClient({ fail: 500 }).client.getLeaderboard(lb))).kind).toBe("unknown");
  });
});
