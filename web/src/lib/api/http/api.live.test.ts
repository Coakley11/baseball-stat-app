/**
 * Live integration tests: the HTTP adapter against a running Baseball API over real data.
 *   BASEBALL_API_ORIGIN=http://127.0.0.1:8601 npm run test:live
 * Also the tripwire for the interim catalog (until handoff R1): every interim value must equal
 * what the live API reports.
 */
import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/generated/baseball-api";
import meta from "../../../../openapi/baseball-api.meta.json";

import { BaseballApiError } from "../errors";
import { createHttpClient } from "./httpClient";
import {
  HISTORICAL_DEFAULTS,
  HISTORICAL_METRICS,
  interimMetric,
  LEADERBOARD_DEFAULTS,
  LEADERBOARD_METRICS,
} from "./interimCatalog";

type Schemas = components["schemas"];
const ORIGIN = process.env.BASEBALL_API_ORIGIN?.replace(/\/+$/, "");
const API = `${ORIGIN}/api/v1`;

async function raw<T>(path: string): Promise<{ status: number; body: T }> {
  const res = await fetch(`${API}/${path}`);
  return { status: res.status, body: (await res.json()) as T };
}

describe.skipIf(!ORIGIN)(`live Baseball API (pinned ${meta.api_commit})`, () => {
  const client = createHttpClient({ baseUrl: API });

  it("serves the pinned schema", async () => {
    const { body } = await raw<{ info: { version: string }; paths: Record<string, unknown> }>("openapi.json");
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

  it("interim stat lists equal what the API accepts", async () => {
    const seasons = await raw<Schemas["ErrorResponse"]>("seasons?metric=__none__");
    const leaders = await raw<Schemas["ErrorResponse"]>("leaderboards?metric=__none__");
    expect(seasons.status).toBe(422);
    expect(HISTORICAL_METRICS).toEqual((seasons.body.error.details!.allowed as string[]).filter((m) => m !== "yearID"));
    expect(LEADERBOARD_METRICS).toEqual(leaders.body.error.details!.allowed as string[]);
  });

  it("interim defaults equal what the API applies when nothing is sent", async () => {
    const health = (await raw<Schemas["HealthInfo"]>("health")).body;
    const seasons = (await raw<Schemas["SeasonLeadersResult"]>("seasons")).body;
    const leaders = (await raw<Schemas["LeaderboardResult"]>("leaderboards")).body;
    const catalog = await client.getCatalog();
    expect(catalog.years).toEqual({ start: health.seasons![0], end: health.seasons![1] });
    expect(catalog.historical.yearRange).toEqual({ start: seasons.start, end: seasons.end });
    expect([HISTORICAL_DEFAULTS.metric, HISTORICAL_DEFAULTS.order]).toEqual([seasons.metric.key, seasons.order]);
    expect(catalog.leaderboards.yearRange).toEqual({ start: leaders.start, end: leaders.end });
    expect(LEADERBOARD_DEFAULTS.metric).toBe(leaders.metric.key);
  });

  it("interim labels and formats equal the API's MetricInfo for every stat", async () => {
    for (const key of LEADERBOARD_METRICS) {
      const path = key === "score" ? "leaderboards?metric=score&limit=1" : `seasons?metric=${encodeURIComponent(key)}&limit=1`;
      const info = (await raw<{ metric: Schemas["MetricInfo"] }>(path)).body.metric;
      const interim = interimMetric(key);
      expect(interim.label, key).toBe(info.label);
      expect(interim.format, key).toBe(info.kind);
    }
  });

  it("maps a live Historical Explorer answer faithfully", async () => {
    const query = { yearRange: { start: 2010, end: 2025 }, metric: "OPS", order: "desc" as const, playerId: null };
    const [result, direct] = await Promise.all([
      client.getHistoricalExplorer(query),
      raw<Schemas["SeasonLeadersResult"]>("seasons?start=2010&end=2025&metric=OPS&order=desc&limit=25"),
    ]);
    expect(result.answer?.headline).toBe(direct.body.headline);
    expect(result.totalCount).toBe(direct.body.total_rows);
    expect(result.seasons.map((s) => [s.player.id, s.year, s.stats.OPS])).toEqual(
      direct.body.rows.map((r) => [r.player.player_id, r.year, r.stats.OPS]),
    );
    expect(result.qualification.minAtBats).toBe(direct.body.qualification.min_ab);
  });

  it("maps a live leaderboard faithfully", async () => {
    const [result, direct] = await Promise.all([
      client.getLeaderboard({ yearRange: { start: 2020, end: 2025 }, metric: "score" }),
      raw<Schemas["LeaderboardResult"]>("leaderboards?start=2020&end=2025&metric=score&limit=25"),
    ]);
    expect(result.entries.map((e) => [e.rank, e.player.id, e.stats.score])).toEqual(
      direct.body.rows.map((r) => [r.rank, r.player.player_id, r.score]),
    );
    expect(result.score?.weights).toEqual(Object.entries(direct.body.weights).map(([metric, weight]) => ({ metric, weight })));
  });

  it("maps live errors to the page's error kinds", async () => {
    const bad = await client.getLeaderboard({ yearRange: { start: 2020, end: 2025 }, metric: "WAR" }).catch((e: unknown) => e);
    expect(bad).toBeInstanceOf(BaseballApiError);
    expect((bad as BaseballApiError).kind).toBe("invalid_request");
    const range = await client.getHistoricalExplorer({ yearRange: { start: 2030, end: 2031 }, metric: "HR", order: "desc", playerId: null }).catch((e: unknown) => e);
    expect((range as BaseballApiError).kind).toBe("invalid_request");
  });

  it("searches players live", async () => {
    const players = await client.searchPlayers("judge");
    expect(players.some((p) => p.id === "judgeaa01")).toBe(true);
  });
});
