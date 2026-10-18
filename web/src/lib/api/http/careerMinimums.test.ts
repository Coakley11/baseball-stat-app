import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/generated/baseball-api";
import { createRecordedClient, recorded } from "@/test/recordedApi";

import { NO_HISTORICAL_FILTERS } from "../types";

type Schemas = components["schemas"];

const HE = "seasons?start=2010&end=2025&metric=HR&order=desc&limit=25";
const HE_OPS = "seasons?start=2010&end=2025&metric=OPS&order=desc&limit=25";
const he = { yearRange: { start: 2010, end: 2025 }, metric: "HR", order: "desc" as const, playerId: null };
const lb = { yearRange: { start: 2020, end: 2025 }, metric: "score" };

const CAREER = "seasons?metric=OPS&order=desc&player_id=cabremi01&limit=25&include_below_minimum=true";
const FROM_ONLY = "seasons?start=2015&metric=OPS&order=desc&player_id=cabremi01&limit=25&include_below_minimum=true";
const TO_ONLY = "seasons?end=2008&metric=OPS&order=desc&player_id=cabremi01&limit=25&include_below_minimum=true";
const BOTH = "seasons?start=2015&end=2020&metric=OPS&order=desc&player_id=cabremi01&limit=25&include_below_minimum=true";
const cabrera = { ...he, metric: "OPS", playerId: "cabremi01" };
const sent = (fetchImpl: { mock: { calls: unknown[][] } }) => fetchImpl.mock.calls.map(([url]) => String(url));

describe("one player's career (5ca7a26)", () => {
  it("with no chosen bounds, leaves the years out so the API uses the player's career", async () => {
    const raw = recorded<Schemas["SeasonLeadersResult"]>(CAREER);
    const { client, fetchImpl } = createRecordedClient();
    const result = await client.getHistoricalExplorer({ ...cabrera, explicitRange: { start: false, end: false } });
    expect(sent(fetchImpl).some((u) => u.endsWith(CAREER))).toBe(true);
    expect(sent(fetchImpl).filter((u) => u.includes("player_id")).some((u) => /[?&](start|end)=/.test(u))).toBe(false);
    // The career is whatever the API says it is; nothing is computed here.
    expect(result.query.yearRange).toEqual({ start: raw.start, end: raw.end });
    expect(raw.start).toBeLessThan(2010);
    expect(Math.min(...result.seasons.map((s) => s.year))).toBe(raw.start);
    expect(result.seasons).toHaveLength(raw.rows.length);
  });

  it("includes below-minimum career seasons, unranked", async () => {
    const raw = recorded<Schemas["SeasonLeadersResult"]>(CAREER);
    const result = await createRecordedClient().client.getHistoricalExplorer({ ...cabrera, explicitRange: { start: false, end: false } });
    expect(result.rankedCount).toBe(raw.ranked_rows);
    expect(result.totalCount).toBe(raw.total_rows);
    expect(result.totalCount).toBeGreaterThan(result.rankedCount);
    const below = result.seasons.filter((s) => !s.qualified);
    expect(below).toHaveLength(raw.rows.filter((r) => !r.meets_minimum).length);
    expect(below.length).toBeGreaterThan(0);
    expect(below.every((s) => s.rank === null)).toBe(true);
  });

  it("sends only the bounds the user chose", async () => {
    const { client, fetchImpl } = createRecordedClient();
    const fromOnly = await client.getHistoricalExplorer({ ...cabrera, yearRange: { start: 2015, end: 2025 }, explicitRange: { start: true, end: false } });
    expect(sent(fetchImpl).some((u) => u.endsWith(FROM_ONLY))).toBe(true);
    expect(fromOnly.query.yearRange).toEqual({ start: 2015, end: recorded<Schemas["SeasonLeadersResult"]>(FROM_ONLY).end });

    await client.getHistoricalExplorer({ ...cabrera, yearRange: { start: 2010, end: 2008 }, explicitRange: { start: false, end: true } });
    expect(sent(fetchImpl).some((u) => u.endsWith(TO_ONLY))).toBe(true);

    const both = await client.getHistoricalExplorer({ ...cabrera, yearRange: { start: 2015, end: 2020 }, explicitRange: { start: true, end: true } });
    expect(sent(fetchImpl).some((u) => u.endsWith(BOTH))).toBe(true);
    expect(both.query.yearRange).toEqual({ start: 2015, end: 2020 });
    expect(both.seasons.every((s) => s.year >= 2015 && s.year <= 2020)).toBe(true);
  });

  it("all players always send the range, whatever was marked as chosen", async () => {
    const { client, fetchImpl } = createRecordedClient();
    await client.getHistoricalExplorer({ ...he, explicitRange: { start: false, end: false } });
    expect(sent(fetchImpl).some((u) => u.endsWith(HE))).toBe(true);
  });
});

describe("minimums the user sets (5ca7a26)", () => {
  const HR_500 = "seasons?start=2010&end=2025&metric=HR&order=desc&min_ab=500&limit=25";
  const OPS_BOTH = "seasons?start=2010&end=2025&metric=OPS&order=desc&min_ab=300&min_HR=30&limit=25";
  const OPS_ZERO = "seasons?start=2010&end=2025&metric=OPS&order=desc&min_ab=0&limit=25";

  it("Historical Explorer: min_ab and stat minimums go to the API; its qualification and totals come back unchanged", async () => {
    const { client, fetchImpl } = createRecordedClient();

    const hr = await client.getHistoricalExplorer({ ...he, minimums: { ab: 500, stats: {} } });
    expect(sent(fetchImpl).some((u) => u.endsWith(HR_500))).toBe(true);
    expect(hr.totalCount).toBe(recorded<Schemas["SeasonLeadersResult"]>(HR_500).total_rows);
    expect(hr.totalCount).toBeLessThan(recorded<Schemas["SeasonLeadersResult"]>(HE).total_rows);

    const ops = await client.getHistoricalExplorer({ ...he, metric: "OPS", minimums: { ab: 300, stats: { HR: 30 } } });
    const rawOps = recorded<Schemas["SeasonLeadersResult"]>(OPS_BOTH);
    expect(ops.qualification).toMatchObject({ kind: "manual", summary: rawOps.qualification.summary, minAtBats: 300 });
    expect(ops.qualification.summary).toBe("Minimum you set · at least 300 AB in the season");
    expect(ops.totalCount).toBe(rawOps.total_rows);
  });

  it("0 means no minimum: the API says so, and ranks more seasons than the default", async () => {
    const { client, fetchImpl } = createRecordedClient();
    const zero = await client.getHistoricalExplorer({ ...he, metric: "OPS", minimums: { ab: 0, stats: {} } });
    expect(sent(fetchImpl).some((u) => u.endsWith(OPS_ZERO))).toBe(true);
    expect(zero.qualification.kind).toBe("none");
    expect(zero.qualification.summary).toBe(recorded<Schemas["SeasonLeadersResult"]>(OPS_ZERO).qualification.summary);
    expect(zero.totalCount).toBeGreaterThan(recorded<Schemas["SeasonLeadersResult"]>(HE_OPS).total_rows);
  });

  it("no minimums set sends nothing extra, so the API keeps its automatic qualified minimum", async () => {
    const { client, fetchImpl } = createRecordedClient();
    const result = await client.getHistoricalExplorer({ ...he, metric: "OPS", minimums: { ab: null, stats: {} } });
    expect(sent(fetchImpl).some((u) => u.endsWith(HE_OPS))).toBe(true);
    expect(result.qualification.kind).toBe("qualified");
  });

  it("Leaderboards minimums are API parameters too", async () => {
    const LB_1000 = "leaderboards?start=2020&end=2025&metric=OPS&min_ab=1000&limit=25";
    const LB_BOTH = "leaderboards?start=2020&end=2025&metric=OPS&min_ab=1000&min_HR=100&limit=25";
    const { client, fetchImpl } = createRecordedClient();
    const result = await client.getLeaderboard({ ...lb, metric: "OPS", minimums: { ab: 1000, stats: {} } });
    expect(sent(fetchImpl).some((u) => u.endsWith(LB_1000))).toBe(true);
    expect(result.totalRanked).toBe(recorded<Schemas["LeaderboardResult"]>(LB_1000).total_rows);
    expect(result.qualification.summary).toBe(recorded<Schemas["LeaderboardResult"]>(LB_1000).qualification.summary);
    const more = await client.getLeaderboard({ ...lb, metric: "OPS", minimums: { ab: 1000, stats: { HR: 100 } } });
    expect(more.totalRanked).toBe(recorded<Schemas["LeaderboardResult"]>(LB_BOTH).total_rows);
    expect(more.totalRanked).toBeLessThan(result.totalRanked);
  });

  it("a manual minimum on a counting stat filters, though the API words nothing about it", async () => {
    const { client } = createRecordedClient();
    const hr = await client.getHistoricalExplorer({ ...he, minimums: { ab: 500, stats: {} } });
    const raw = recorded<Schemas["SeasonLeadersResult"]>(HR_500);
    expect(raw.qualification).toMatchObject({ mode: "manual", min_ab: 500, summary: "" });
    expect(hr.qualification.summary).toBeNull(); // nothing is made up for it
  });
});

describe("several franchises (5ca7a26)", () => {
  const key = (teams: string) => `seasons?start=2010&end=2025&metric=HR&order=desc&teams=${teams}&limit=25`;

  it("are one API list: any of them, as the API unions them", async () => {
    const both = "Boston+Red+Sox%2CNew+York+Yankees";
    const { client, fetchImpl } = createRecordedClient();
    const result = await client.getHistoricalExplorer({ ...he, filters: { ...NO_HISTORICAL_FILTERS, teams: ["Boston Red Sox", "New York Yankees"] } });
    expect(sent(fetchImpl).some((u) => u.endsWith(key(both)))).toBe(true);
    const boston = recorded<Schemas["SeasonLeadersResult"]>(key("Boston+Red+Sox")).total_rows;
    const yankees = recorded<Schemas["SeasonLeadersResult"]>(key("New+York+Yankees")).total_rows;
    // The API's own numbers, compared here; the adapter adds nothing up.
    expect(result.totalCount).toBe(boston + yankees);
    expect(result.seasons.every((s) => ["New York Yankees", "Boston Red Sox"].includes(s.teamName ?? ""))).toBe(true);
  });

  it("a league and a franchise together are a union (more than the league alone)", async () => {
    const { client } = createRecordedClient();
    const result = await client.getHistoricalExplorer({ ...he, filters: { ...NO_HISTORICAL_FILTERS, teams: ["American League", "Chicago Cubs"] } });
    expect(result.totalCount).toBe(recorded<Schemas["SeasonLeadersResult"]>(key("American+League%2CChicago+Cubs")).total_rows);
  });
});

describe("exports follow the question (5ca7a26)", () => {
  it("carry the same minimums, filters and unchosen years as the table", () => {
    const { client } = createRecordedClient();
    const url = client.historicalExportUrl({
      ...cabrera,
      yearRange: { start: 2010, end: 2025 },
      explicitRange: { start: false, end: false },
      minimums: { ab: 300, stats: { HR: 30 } },
      filters: { ...NO_HISTORICAL_FILTERS, teams: ["Boston Red Sox"] },
      offset: 25,
    });
    expect(url).toBe("http://recorded.test/api/v1/seasons?metric=OPS&order=desc&teams=Boston+Red+Sox&player_id=cabremi01&min_ab=300&min_HR=30&format=csv");
    expect(client.leaderboardExportUrl({ ...lb, metric: "OPS", limit: 25, minimums: { ab: 1000, stats: { HR: 100 } } })).toBe(
      "http://recorded.test/api/v1/leaderboards?start=2020&end=2025&metric=OPS&min_ab=1000&min_HR=100&limit=25&format=csv",
    );
  });
});
