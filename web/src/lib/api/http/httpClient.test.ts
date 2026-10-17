import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/generated/baseball-api";
import { createRecordedClient, RECORDED, recorded } from "@/test/recordedApi";

import { BaseballApiError } from "../errors";
import { HISTORICAL_DEFAULTS, HISTORICAL_METRICS, LEADERBOARD_DEFAULTS } from "./interimCatalog";

type Schemas = components["schemas"];
const HE_HR = "seasons?start=2010&end=2025&metric=HR&order=desc&limit=25";
const HE_OPS = "seasons?start=2010&end=2025&metric=OPS&order=desc&limit=25";
const LB_SCORE = "leaderboards?start=2020&end=2025&metric=score&limit=25";
const LB_OPS = "leaderboards?start=2020&end=2025&metric=OPS&limit=25";
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

describe("HTTP adapter over recorded real API responses (a9a80f7)", () => {
  it("is the real API, and does not offer one-player rankings", () => {
    const { client } = createRecordedClient();
    expect(RECORDED.api_commit).toBe("a9a80f7");
    expect(client.source).toBe("api");
    expect(client.capabilities.playerSeasonRanking).toBe(false);
  });

  it("copies the Historical Explorer answer, rows and totals without changing them", async () => {
    const raw = recorded<Schemas["SeasonLeadersResult"]>(HE_HR);
    const result = await createRecordedClient().client.getHistoricalExplorer(he);

    expect(result.answer).toEqual({ headline: raw.headline, detail: null, context: null });
    expect(result.keyMetrics).toEqual([]); // tile selection waits on handoff R2
    expect(result.totalCount).toBe(raw.total_rows);
    expect(result.seasons).toHaveLength(raw.rows.length);
    raw.rows.forEach((row, i) => {
      const season = result.seasons[i]!;
      expect(season.player).toEqual({ id: row.player.player_id, name: row.player.name });
      expect(season.year).toBe(row.year);
      expect(season.team).toBe(row.team?.team_id ?? null);
      expect(season.teamName).toBe(row.team?.season_name ?? row.team?.name ?? null);
      for (const [key, value] of Object.entries(row.stats)) expect(season.stats[key]).toBe(value);
    });
    expect(result.topSeasonId).toBe(result.seasons[0]!.id);
    expect(result.chart?.seasonIds).toEqual(result.seasons.slice(0, 10).map((s) => s.id));
    expect(result.metric).toEqual({ key: "HR", label: raw.metric.label, name: raw.metric.label, format: "count" });
    expect(result.qualification).toEqual({ kind: "not_applicable", summary: null, minAtBats: null, scope: "season" });
  });

  it("takes qualification numbers from the API and never shows its Markdown caption", async () => {
    const raw = recorded<Schemas["SeasonLeadersResult"]>(HE_OPS);
    const result = await createRecordedClient().client.getHistoricalExplorer({ ...he, metric: "OPS" });
    expect(raw.qualification.text).toContain("**");
    expect(result.qualification).toEqual({ kind: "qualified", summary: null, minAtBats: raw.qualification.min_ab, scope: "season" });
    expect(result.metric.format).toBe("rate");
  });

  it("copies the leaderboard ranking and weights, with no invented answer or season counts", async () => {
    const raw = recorded<Schemas["LeaderboardResult"]>(LB_SCORE);
    const result = await createRecordedClient().client.getLeaderboard(lb);

    expect(result.answer).toBeNull(); // handoff R3
    expect(result.totalRanked).toBe(raw.total_rows);
    raw.rows.forEach((row, i) => {
      const entry = result.entries[i]!;
      expect(entry.rank).toBe(row.rank);
      expect(entry.player.id).toBe(row.player.player_id);
      expect(entry.seasons).toBeNull();
      expect(entry.stats.score).toBe(row.score);
      expect(entry.stats.HR).toBe(row.stats.HR);
    });
    expect(result.score).toEqual({ summary: null, weights: Object.entries(raw.weights).map(([metric, weight]) => ({ metric, weight })) });
    expect(result.columns[0]).toBe("score");
  });

  it("carries the span qualification for rate-stat leaderboards", async () => {
    const raw = recorded<Schemas["LeaderboardResult"]>(LB_OPS);
    const result = await createRecordedClient().client.getLeaderboard({ ...lb, metric: "OPS" });
    expect(result.qualification).toEqual({ kind: "qualified", summary: null, minAtBats: raw.qualification.min_ab, scope: "span" });
    expect(result.entries[0]!.player.name).toBe(raw.rows[0]!.player.name);
  });

  it("maps a real empty result to no rows and no answer", async () => {
    const { client } = createRecordedClient({ substitute: { [HE_HR]: `${HE_HR}&min_HR=100` } });
    const result = await client.getHistoricalExplorer(he);
    expect(result.seasons).toEqual([]);
    expect(result.answer).toBeNull();
    expect(result.chart).toBeNull();
  });

  it("builds the catalog from /health and the interim defaults, which match what the API applies", async () => {
    const health = recorded<Schemas["HealthInfo"]>("health");
    const catalog = await createRecordedClient().client.getCatalog();
    expect(catalog.years).toEqual({ start: health.seasons![0], end: health.seasons![1] });

    const seasons = recorded<Schemas["SeasonLeadersResult"]>("seasons");
    expect([HISTORICAL_DEFAULTS.start, HISTORICAL_DEFAULTS.metric, HISTORICAL_DEFAULTS.order]).toEqual([seasons.start, seasons.metric.key, seasons.order]);
    expect(catalog.historical.yearRange).toEqual({ start: seasons.start, end: seasons.end });

    const leaders = recorded<Schemas["LeaderboardResult"]>("leaderboards");
    expect([LEADERBOARD_DEFAULTS.start, LEADERBOARD_DEFAULTS.metric]).toEqual([leaders.start, leaders.metric.key]);
    expect(catalog.leaderboards.yearRange).toEqual({ start: leaders.start, end: leaders.end });

    const allowed = (recorded<Schemas["ErrorResponse"]>("seasons?start=2010&end=2025&metric=WAR&order=desc&limit=25").error.details as { allowed: string[] }).allowed;
    expect(HISTORICAL_METRICS).toEqual(allowed.filter((m) => m !== "yearID"));
  });

  it("uses the API's unique player labels in search results", async () => {
    const raw = recorded<Schemas["PlayerSearchResult"]>("players/search?q=judge&limit=8");
    const players = await createRecordedClient().client.searchPlayers("judge");
    expect(players.map((p) => p.name)).toEqual(raw.results.map((r) => r.player.label));
    expect(players[0]).toMatchObject({ id: raw.results[0]!.player.player_id, firstSeason: raw.results[0]!.first_season });
    expect(await createRecordedClient().client.searchPlayers("j")).toEqual([]);
  });

  it("reads a player's summary, and treats an unknown id as no player", async () => {
    const { client } = createRecordedClient();
    expect((await client.getPlayer("judgeaa01"))?.name).toBe(recorded<Schemas["PlayerSeasonsResult"]>("players/judgeaa01/seasons").player.player.label);
    expect(await client.getPlayer("nobody99")).toBeNull();
  });

  it("maps API errors and transport failures to the page's error kinds", async () => {
    const real422 = await rejection(createRecordedClient().client.getHistoricalExplorer({ ...he, metric: "WAR" }));
    expect(real422.kind).toBe("invalid_request");
    expect(real422.message).toBe(recorded<Schemas["ErrorResponse"]>("seasons?start=2010&end=2025&metric=WAR&order=desc&limit=25").error.message);

    const range = await rejection(createRecordedClient().client.getLeaderboard({ yearRange: { start: 2030, end: 2031 }, metric: "HR" }));
    expect(range.kind).toBe("invalid_request");

    expect((await rejection(createRecordedClient({ fail: "network" }).client.getLeaderboard(lb))).kind).toBe("unavailable");
    expect((await rejection(createRecordedClient({ fail: 503 }).client.getLeaderboard(lb))).kind).toBe("unavailable");
    expect((await rejection(createRecordedClient({ fail: 502 }).client.getLeaderboard(lb))).kind).toBe("unavailable");
    expect((await rejection(createRecordedClient({ fail: 500 }).client.getLeaderboard(lb))).kind).toBe("unknown");
  });

  it("refuses one-player questions instead of computing them", async () => {
    const { client, fetchImpl } = createRecordedClient();
    const error = await rejection(client.getHistoricalExplorer({ ...he, playerId: "judgeaa01" }));
    expect(error.kind).toBe("unsupported");
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
